"""Tests for the entity write path.

``sync_memory_entities`` is the single entry point used by every stage that
writes ``structured_content`` (capture, refinement, enrichment). It must:

- create mentions for entities the memory now contains,
- give the *same* person the *same* entity across memories,
- **remove** mentions that are no longer present (reprocessing rewrites the
  whole content, so stale mentions must not linger),
- keep denormalized counts accurate, and
- preserve the user-supplied ``role`` ("wife") from metadata.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.db import Base, User, Memory, Entity, MemoryEntity, EntityAlias
from app.db.entities import (
    extract_mentions,
    sync_memory_entities,
    apply_mentions,
)


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def user(test_db):
    user = User(username="alice", email="alice@example.com", password_hash="h")
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def _make_memory(session, user_id, content=None, text="memory"):
    memory = Memory(
        raw_input=text,
        input_type="text",
        user_id=user_id,
        structured_content=content or {"title": "t", "summary": text},
        tags=[],
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestExtractMentions:
    """structured_content -> (kind, surface_form, role) triples."""

    def test_extracts_person_with_role_from_metadata(self):
        content = {
            "entities": [
                {"type": "person", "value": "Dawn", "metadata": {"relation": "wife"}}
            ]
        }
        assert extract_mentions(content) == [("person", "Dawn", "wife")]

    def test_extracts_place_and_organization(self):
        content = {
            "entities": [
                {"type": "place", "value": "Denver", "metadata": None},
                {"type": "organization", "value": "Google", "metadata": None},
            ]
        }
        assert extract_mentions(content) == [
            ("place", "Denver", None),
            ("organization", "Google", None),
        ]

    def test_ignores_date_event_and_concept(self):
        content = {
            "entities": [
                {"type": "date", "value": "1976", "metadata": None},
                {"type": "event", "value": "the wedding", "metadata": None},
                {"type": "concept", "value": "grief", "metadata": None},
            ]
        }
        assert extract_mentions(content) == []

    def test_tolerates_missing_or_malformed_entities(self):
        assert extract_mentions(None) == []
        assert extract_mentions({}) == []
        assert extract_mentions({"entities": "nope"}) == []
        assert extract_mentions({"entities": ["not-a-dict", 42]}) == []
        assert extract_mentions({"entities": [{"type": "person"}]}) == []

    def test_role_falls_back_to_role_key(self):
        content = {
            "entities": [
                {"type": "person", "value": "Mike", "metadata": {"role": "brother"}}
            ]
        }
        assert extract_mentions(content) == [("person", "Mike", "brother")]


class TestSyncCreatesMentions:
    """Capture attaches entities."""

    @pytest.mark.asyncio
    async def test_capture_content_creates_entities_and_mentions(
        self, test_db, user
    ):
        memory = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "Coffee",
                "summary": "Coffee with Sarah in Denver.",
                "entities": [
                    {"type": "person", "value": "Sarah", "metadata": None},
                    {"type": "place", "value": "Denver", "metadata": None},
                ],
            },
        )

        entities = await sync_memory_entities(
            test_db, str(user.id), str(memory.id), memory.structured_content
        )
        await test_db.commit()

        assert len(entities) == 2
        result = await test_db.execute(select(Entity))
        assert {e.canonical_name for e in result.scalars().all()} == {"Sarah", "Denver"}

        mentions = (await test_db.execute(select(MemoryEntity))).scalars().all()
        assert len(mentions) == 2


class TestSyncIsIdempotentAndRemoves:
    """Re-running sync must converge on the current content exactly."""

    @pytest.mark.asyncio
    async def test_rerunning_same_content_is_stable(self, test_db, user):
        memory = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "t",
                "summary": "s",
                "entities": [{"type": "person", "value": "Sarah", "metadata": None}],
            },
        )

        await sync_memory_entities(
            test_db, str(user.id), str(memory.id), memory.structured_content
        )
        await sync_memory_entities(
            test_db, str(user.id), str(memory.id), memory.structured_content
        )
        await test_db.commit()

        mentions = (await test_db.execute(select(MemoryEntity))).scalars().all()
        assert len(mentions) == 1
        entity = (await test_db.execute(select(Entity))).scalars().one()
        assert entity.mention_count == 1

    @pytest.mark.asyncio
    async def test_reprocessing_removes_entities_no_longer_mentioned(
        self, test_db, user
    ):
        """Reprocessing replaces content, so dropped entities must detach."""
        memory = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "t",
                "summary": "s",
                "entities": [
                    {"type": "person", "value": "Sarah", "metadata": None},
                    {"type": "place", "value": "Denver", "metadata": None},
                ],
            },
        )
        await sync_memory_entities(
            test_db, str(user.id), str(memory.id), memory.structured_content
        )
        await test_db.commit()

        # Reprocess: the new content only mentions Sarah.
        new_content = {
            "title": "t2",
            "summary": "s2",
            "entities": [{"type": "person", "value": "Sarah", "metadata": None}],
        }
        memory.structured_content = new_content
        await test_db.commit()

        await sync_memory_entities(
            test_db, str(user.id), str(memory.id), new_content
        )
        await test_db.commit()

        mentions = (await test_db.execute(select(MemoryEntity))).scalars().all()
        assert len(mentions) == 1

        # Denver's entity still exists but is no longer mentioned here.
        denver = (
            await test_db.execute(select(Entity).where(Entity.canonical_name == "Denver"))
        ).scalars().one()
        assert denver.mention_count == 0

    @pytest.mark.asyncio
    async def test_shared_person_across_memories_stays_one_entity(
        self, test_db, user
    ):
        m1 = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "a",
                "summary": "a",
                "entities": [{"type": "person", "value": "Sarah", "metadata": None}],
            },
        )
        m2 = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "b",
                "summary": "b",
                "entities": [
                    {"type": "person", "value": "Sarah's", "metadata": None}
                ],
            },
        )

        await sync_memory_entities(
            test_db, str(user.id), str(m1.id), m1.structured_content
        )
        await sync_memory_entities(
            test_db, str(user.id), str(m2.id), m2.structured_content
        )
        await test_db.commit()

        entities = (await test_db.execute(select(Entity))).scalars().all()
        assert len(entities) == 1
        assert entities[0].mention_count == 2


class TestSyncRoles:
    """Roles come from metadata and must persist on the mention."""

    @pytest.mark.asyncio
    async def test_role_is_recorded(self, test_db, user):
        memory = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "t",
                "summary": "s",
                "entities": [
                    {"type": "person", "value": "Dawn", "metadata": {"relation": "wife"}}
                ],
            },
        )

        await sync_memory_entities(
            test_db, str(user.id), str(memory.id), memory.structured_content
        )
        await test_db.commit()

        mention = (await test_db.execute(select(MemoryEntity))).scalars().one()
        assert mention.role == "wife"


class TestSyncCountsAcrossMemories:
    """Counts reflect the true number of mentioning memories."""

    @pytest.mark.asyncio
    async def test_count_drops_when_a_mention_is_removed(self, test_db, user):
        m1 = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "a",
                "summary": "a",
                "entities": [{"type": "person", "value": "Sarah", "metadata": None}],
            },
        )
        m2 = await _make_memory(
            test_db,
            str(user.id),
            content={
                "title": "b",
                "summary": "b",
                "entities": [{"type": "person", "value": "Sarah", "metadata": None}],
            },
        )
        await sync_memory_entities(
            test_db, str(user.id), str(m1.id), m1.structured_content
        )
        await sync_memory_entities(
            test_db, str(user.id), str(m2.id), m2.structured_content
        )
        await test_db.commit()

        assert (await test_db.execute(select(Entity))).scalars().one().mention_count == 2

        # m2 is reprocessed and no longer mentions Sarah.
        await sync_memory_entities(test_db, str(user.id), str(m2.id), {})
        await test_db.commit()

        assert (await test_db.execute(select(Entity))).scalars().one().mention_count == 1


class TestCaptureIntegration:
    """The full capture endpoint must create first-class entities."""

    @pytest.mark.asyncio
    async def test_text_capture_creates_queryable_entities(
        self, test_db, user, monkeypatch
    ):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db import get_db
        from app.models.schemas import StructuredMemory, EntityData
        from app.security import create_access_token

        # Capture runs through the real route plus the worker, so point the
        # background session factory at the same test database.
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from app.jobs import scheduler as scheduler_module

        factory = async_sessionmaker(
            bind=test_db.bind,
            class_=type(test_db),
            expire_on_commit=False,
            autoflush=False,
        )
        original = scheduler_module.BackgroundSessionLocal
        scheduler_module.BackgroundSessionLocal = factory

        async def override_get_db():
            yield test_db

        app.dependency_overrides[get_db] = override_get_db

        async def fake_structure(raw_input: str) -> StructuredMemory:
            return StructuredMemory(
                title="Coffee with Dawn",
                summary=raw_input,
                entities=[
                    EntityData(
                        type="person", value="Dawn", metadata={"relation": "wife"}
                    ),
                    EntityData(type="place", value="Raleigh", metadata=None),
                ],
                mood="happy",
                importance_level=6,
                initial_tags=["coffee"],
            )

        monkeypatch.setattr("app.routes.memories.structure_memory", fake_structure)

        token = create_access_token(user_id=str(user.id), username=user.username)

        try:
            client = TestClient(app)
            response = client.post(
                "/api/memories/capture/text",
                json={"raw_input": "Coffee with Dawn in Raleigh."},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 201
        finally:
            scheduler_module.BackgroundSessionLocal = original
            app.dependency_overrides.pop(get_db, None)

        # Entities are now first-class and queryable.
        people = (
            await test_db.execute(select(Entity).where(Entity.kind == "person"))
        ).scalars().all()
        places = (
            await test_db.execute(select(Entity).where(Entity.kind == "place"))
        ).scalars().all()
        assert [e.canonical_name for e in people] == ["Dawn"]
        assert [e.canonical_name for e in places] == ["Raleigh"]

        mentions = (await test_db.execute(select(MemoryEntity))).scalars().all()
        assert len(mentions) >= 1
