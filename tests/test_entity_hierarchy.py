"""Tests for place/person containment inference (parent_entity_id).

The capture agent may emit a ``parent`` hint on an entity's metadata, e.g. a
café inside a city:

    {"type": "place", "value": "Bluebird Cafe",
     "metadata": {"parent": "Denver"}}

``extract_parent_links`` pulls those hints out, and ``sync_memory_entities``
resolves them: the parent is found-or-created and the child's
``parent_entity_id`` is set. Resolution must never create cycles or point an
entity at itself.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.db import Base, User, Memory, Entity
from app.db.entities import (
    extract_parent_links,
    sync_memory_entities,
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


async def _memory_with_content(session, user_id, content):
    memory = Memory(
        raw_input="m",
        input_type="text",
        user_id=user_id,
        structured_content=content,
        tags=[],
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def _entity(session, name, kind=None):
    stmt = select(Entity).where(Entity.canonical_name == name)
    if kind:
        stmt = stmt.where(Entity.kind == kind)
    return (await session.execute(stmt)).scalars().first()


class TestCapturePromptDocumentsParent:
    """The capture agent must be told to emit containment hints."""

    def test_prompt_mentions_metadata_parent(self):
        from app.agents.capture import CAPTURE_SYSTEM_PROMPT

        assert '"parent"' in CAPTURE_SYSTEM_PROMPT
        assert "nested place" in CAPTURE_SYSTEM_PROMPT.lower()

    def test_prompt_mentions_relation_metadata(self):
        from app.agents.capture import CAPTURE_SYSTEM_PROMPT

        assert '"relation"' in CAPTURE_SYSTEM_PROMPT


class TestExtractParentLinks:
    """structured_content -> (child, parent) name pairs."""

    def test_extracts_parent_hint_from_metadata(self):
        content = {
            "entities": [
                {
                    "type": "place",
                    "value": "Bluebird Cafe",
                    "metadata": {"parent": "Denver"},
                }
            ]
        }
        assert extract_parent_links(content) == [("Bluebird Cafe", "Denver")]

    def test_ignores_entities_without_a_parent(self):
        content = {
            "entities": [
                {"type": "place", "value": "Denver", "metadata": None},
                {"type": "person", "value": "Sarah", "metadata": {"relation": "friend"}},
            ]
        }
        assert extract_parent_links(content) == []

    def test_ignores_non_place_children(self):
        """A person is not contained by a place; only places nest."""
        content = {
            "entities": [
                {
                    "type": "person",
                    "value": "Sarah",
                    "metadata": {"parent": "Denver"},
                }
            ]
        }
        assert extract_parent_links(content) == []

    def test_ignores_self_parent(self):
        content = {
            "entities": [
                {"type": "place", "value": "Denver", "metadata": {"parent": "Denver"}}
            ]
        }
        assert extract_parent_links(content) == []

    def test_tolerates_malformed_input(self):
        assert extract_parent_links(None) == []
        assert extract_parent_links({}) == []
        assert extract_parent_links({"entities": "nope"}) == []
        assert extract_parent_links({"entities": [{"type": "place"}]}) == []


class TestParentResolution:
    """sync_memory_entities applies parent hints."""

    @pytest.mark.asyncio
    async def test_child_links_to_parent(self, test_db, user):
        content = {
            "title": "t",
            "summary": "s",
            "entities": [
                {"type": "place", "value": "Denver", "metadata": None},
                {
                    "type": "place",
                    "value": "Bluebird Cafe",
                    "metadata": {"parent": "Denver"},
                },
            ],
        }
        memory = await _memory_with_content(test_db, str(user.id), content)

        await sync_memory_entities(test_db, str(user.id), str(memory.id), content)
        await test_db.commit()

        cafe = await _entity(test_db, "Bluebird Cafe")
        denver = await _entity(test_db, "Denver")
        assert str(cafe.parent_entity_id) == str(denver.id)

    @pytest.mark.asyncio
    async def test_parent_is_created_if_not_mentioned(self, test_db, user):
        """The parent need not appear as its own entity in the memory."""
        content = {
            "title": "t",
            "summary": "s",
            "entities": [
                {
                    "type": "place",
                    "value": "Bluebird Cafe",
                    "metadata": {"parent": "Denver"},
                }
            ],
        }
        memory = await _memory_with_content(test_db, str(user.id), content)

        await sync_memory_entities(test_db, str(user.id), str(memory.id), content)
        await test_db.commit()

        denver = await _entity(test_db, "Denver")
        assert denver is not None
        assert denver.kind == "place"
        cafe = await _entity(test_db, "Bluebird Cafe")
        assert str(cafe.parent_entity_id) == str(denver.id)

    @pytest.mark.asyncio
    async def test_existing_parent_is_reused_not_duplicated(self, test_db, user):
        first = {
            "title": "a",
            "summary": "a",
            "entities": [
                {"type": "place", "value": "Denver", "metadata": None},
                {"type": "place", "value": "Cafe A", "metadata": {"parent": "Denver"}},
            ],
        }
        second = {
            "title": "b",
            "summary": "b",
            "entities": [
                {"type": "place", "value": "Cafe B", "metadata": {"parent": "Denver"}},
            ],
        }
        m1 = await _memory_with_content(test_db, str(user.id), first)
        m2 = await _memory_with_content(test_db, str(user.id), second)

        await sync_memory_entities(test_db, str(user.id), str(m1.id), first)
        await sync_memory_entities(test_db, str(user.id), str(m2.id), second)
        await test_db.commit()

        denvers = (
            await test_db.execute(select(Entity).where(Entity.canonical_name == "Denver"))
        ).scalars().all()
        assert len(denvers) == 1

        cafe_a = await _entity(test_db, "Cafe A")
        cafe_b = await _entity(test_db, "Cafe B")
        assert str(cafe_a.parent_entity_id) == str(denvers[0].id)
        assert str(cafe_b.parent_entity_id) == str(denvers[0].id)

    @pytest.mark.asyncio
    async def test_resolution_is_idempotent(self, test_db, user):
        content = {
            "title": "t",
            "summary": "s",
            "entities": [
                {
                    "type": "place",
                    "value": "Bluebird Cafe",
                    "metadata": {"parent": "Denver"},
                }
            ],
        }
        memory = await _memory_with_content(test_db, str(user.id), content)

        await sync_memory_entities(test_db, str(user.id), str(memory.id), content)
        await sync_memory_entities(test_db, str(user.id), str(memory.id), content)
        await test_db.commit()

        places = (
            await test_db.execute(select(Entity).where(Entity.kind == "place"))
        ).scalars().all()
        assert len(places) == 2  # cafe + denver, no duplicates

    @pytest.mark.asyncio
    async def test_cycle_is_not_created(self, test_db, user):
        """Mutual parents must not both be set."""
        content = {
            "title": "t",
            "summary": "s",
            "entities": [
                {"type": "place", "value": "A", "metadata": {"parent": "B"}},
                {"type": "place", "value": "B", "metadata": {"parent": "A"}},
            ],
        }
        memory = await _memory_with_content(test_db, str(user.id), content)

        await sync_memory_entities(test_db, str(user.id), str(memory.id), content)
        await test_db.commit()

        a = await _entity(test_db, "A")
        b = await _entity(test_db, "B")
        # At most one direction may be set; never both.
        assert not (
            a.parent_entity_id is not None and b.parent_entity_id is not None
        )
