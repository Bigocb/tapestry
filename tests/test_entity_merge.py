"""Tests for entity merging and undo.

Merging folds entity B into entity A: its mentions and aliases move to A, and
B becomes a tombstone (``merged_into_id`` set) that every query filters out.
The merge is reversible because the exact moved row ids are recorded, so an
undo restores precisely what changed rather than guessing.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.db import (
    Base,
    User,
    Memory,
    Entity,
    EntityAlias,
    MemoryEntity,
    EntityMerge,
)
from app.db.entities import (
    sync_memory_entities,
    merge_entities,
    undo_merge,
    find_entity_by_alias,
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


async def _memory_with(session, user_id, entities, title="m"):
    content = {
        "title": title,
        "summary": title,
        "entities": [
            {"type": kind, "value": value, "metadata": metadata}
            for kind, value, metadata in entities
        ],
    }
    memory = Memory(
        raw_input=title,
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
    await sync_memory_entities(session, str(user_id), str(memory.id), content)
    await session.commit()
    return memory


async def _entity(session, name, kind="person"):
    result = await session.execute(
        select(Entity).where(Entity.canonical_name == name, Entity.kind == kind)
    )
    return result.scalars().first()


class TestMerge:
    """merge_entities folds source into target and records an audit trail."""

    @pytest.mark.asyncio
    async def test_mentions_move_to_target(self, test_db, user):
        # "Sarah" appears in one memory, "Sarah Smith" in another.
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()

        # All mentions now point at the target.
        mentions = (await test_db.execute(select(MemoryEntity))).scalars().all()
        assert all(str(m.entity_id) == str(sarah.id) for m in mentions)
        assert len(mentions) == 2

    @pytest.mark.asyncio
    async def test_source_becomes_a_tombstone(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()
        await test_db.refresh(sarah_smith)

        assert str(sarah_smith.merged_into_id) == str(sarah.id)
        # The source row is kept, not deleted.
        result = await test_db.execute(select(Entity).where(Entity.id == sarah_smith.id))
        assert result.scalars().first() is not None

    @pytest.mark.asyncio
    async def test_source_alias_now_resolves_to_target(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()

        # Future captures of "Sarah Smith" must find the target entity, so a
        # merge actually prevents the duplicate from coming back.
        found = await find_entity_by_alias(
            test_db, str(user.id), "person", "sarah smith"
        )
        assert found is not None
        assert str(found.id) == str(sarah.id)

    @pytest.mark.asyncio
    async def test_target_count_includes_moved_mentions(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()
        await test_db.refresh(sarah)

        assert sarah.mention_count == 2

    @pytest.mark.asyncio
    async def test_audit_record_is_written(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        merge = await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()

        assert str(merge.source_entity_id) == str(sarah_smith.id)
        assert str(merge.target_entity_id) == str(sarah.id)
        assert len(merge.moved_mention_ids) == 1
        assert len(merge.moved_alias_ids) == 1

    @pytest.mark.asyncio
    async def test_merge_of_same_entity_is_rejected(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        sarah = await _entity(test_db, "Sarah")

        with pytest.raises(ValueError):
            await merge_entities(
                test_db, str(user.id), source_id=str(sarah.id), target_id=str(sarah.id)
            )


class TestUndoMerge:
    """undo_merge restores exactly what was moved."""

    @pytest.mark.asyncio
    async def test_undo_restores_mentions_and_tombstone(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        merge = await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()

        await undo_merge(test_db, str(user.id), str(merge.id))
        await test_db.commit()

        await test_db.refresh(sarah_smith)
        assert sarah_smith.merged_into_id is None

        # Each entity owns its original mention again.
        sarah_mentions = (
            await test_db.execute(
                select(MemoryEntity).where(MemoryEntity.entity_id == sarah.id)
            )
        ).scalars().all()
        smith_mentions = (
            await test_db.execute(
                select(MemoryEntity).where(MemoryEntity.entity_id == sarah_smith.id)
            )
        ).scalars().all()
        assert len(sarah_mentions) == 1
        assert len(smith_mentions) == 1

    @pytest.mark.asyncio
    async def test_undo_restores_alias_lookup(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        merge = await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()
        await undo_merge(test_db, str(user.id), str(merge.id))
        await test_db.commit()

        found = await find_entity_by_alias(
            test_db, str(user.id), "person", "sarah smith"
        )
        assert found is not None
        assert str(found.id) == str(sarah_smith.id)

    @pytest.mark.asyncio
    async def test_undo_twice_is_rejected(self, test_db, user):
        """An audit record is consumed once, so undo cannot be replayed."""
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        merge = await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()
        await undo_merge(test_db, str(user.id), str(merge.id))
        await test_db.commit()

        with pytest.raises(ValueError):
            await undo_merge(test_db, str(user.id), str(merge.id))

    @pytest.mark.asyncio
    async def test_undo_restores_counts(self, test_db, user):
        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(user.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        sarah_smith = await _entity(test_db, "Sarah Smith")

        merge = await merge_entities(
            test_db, str(user.id), source_id=str(sarah_smith.id), target_id=str(sarah.id)
        )
        await test_db.commit()
        await undo_merge(test_db, str(user.id), str(merge.id))
        await test_db.commit()

        await test_db.refresh(sarah)
        await test_db.refresh(sarah_smith)
        assert sarah.mention_count == 1
        assert sarah_smith.mention_count == 1


class TestMergeScoping:
    """Merges must not cross users or kinds."""

    @pytest.mark.asyncio
    async def test_cannot_merge_across_users(self, test_db, user):
        other = User(username="bob", email="bob@example.com", password_hash="h")
        test_db.add(other)
        await test_db.commit()
        await test_db.refresh(other)

        await _memory_with(test_db, str(user.id), [("person", "Sarah", None)], "a")
        await _memory_with(test_db, str(other.id), [("person", "Sarah Smith", None)], "b")

        sarah = await _entity(test_db, "Sarah")
        smith = await _entity(test_db, "Sarah Smith")

        with pytest.raises(ValueError):
            await merge_entities(
                test_db, str(user.id), source_id=str(smith.id), target_id=str(sarah.id)
            )

    @pytest.mark.asyncio
    async def test_cannot_merge_across_kinds(self, test_db, user):
        """A person "Paris" and the city "Paris" are different things."""
        await _memory_with(test_db, str(user.id), [("person", "Paris", None)], "a")
        await _memory_with(test_db, str(user.id), [("place", "Paris", None)], "b")

        person = await _entity(test_db, "Paris", kind="person")
        place = await _entity(test_db, "Paris", kind="place")

        with pytest.raises(ValueError):
            await merge_entities(
                test_db,
                str(user.id),
                source_id=str(place.id),
                target_id=str(person.id),
            )
