"""Tests for splitting an entity (Issue 40).

Merge already has an undo, but that only reverses a *merge*. When extraction
reads two different people as one, no merge ever happened and there is nothing
to undo — which is the case splitting exists for.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db import Base, Memory, User
from app.db.models import Entity, MemoryEntity
from app.db.entities import (
    find_entity_by_alias,
    merge_entities,
    split_entity,
    sync_memory_entities,
    undo_split,
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


async def _mentions(session, entity):
    result = await session.execute(
        select(MemoryEntity).where(MemoryEntity.entity_id == entity.id)
    )
    return result.scalars().all()


class TestSplitEntity:
    """Move chosen memories off an entity onto a new one of the same kind."""

    @pytest.mark.asyncio
    async def test_chosen_memories_move_to_a_new_entity(self, test_db, user):
        first = await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        second = await _memory_with(test_db, user.id, [("person", "Dave", None)], "two")
        dave = await _entity(test_db, "Dave")

        moving = [
            m for m in await _mentions(test_db, dave) if str(m.memory_id) == str(second.id)
        ]
        split = await split_entity(
            test_db, str(user.id), str(dave.id), [str(moving[0].id)], "Dave Smith"
        )
        await test_db.commit()

        new_entity = await test_db.get(Entity, split.new_entity_id)
        assert new_entity.canonical_name == "Dave Smith"
        assert new_entity.kind == "person"

        assert [str(m.memory_id) for m in await _mentions(test_db, new_entity)] == [
            str(second.id)
        ]
        assert [str(m.memory_id) for m in await _mentions(test_db, dave)] == [
            str(first.id)
        ]

    @pytest.mark.asyncio
    async def test_both_counts_are_recomputed(self, test_db, user):
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "two")
        dave = await _entity(test_db, "Dave")

        split = await split_entity(
            test_db,
            str(user.id),
            str(dave.id),
            [str(m.id) for m in await _mentions(test_db, dave)][:1],
            "Dave Smith",
        )
        await test_db.commit()

        new_entity = await test_db.get(Entity, split.new_entity_id)
        assert dave.mention_count == 1
        assert new_entity.mention_count == 1

    @pytest.mark.asyncio
    async def test_an_alias_moves_only_when_nothing_kept_still_uses_it(
        self, test_db, user
    ):
        """Aliases only accumulate through a merge, so this starts with one."""
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        await _memory_with(
            test_db, user.id, [("person", "Dave Smith", None)], "two"
        )
        dave = await _entity(test_db, "Dave")
        dave_smith = await _entity(test_db, "Dave Smith")
        await merge_entities(
            test_db, str(user.id), str(dave_smith.id), str(dave.id)
        )
        await test_db.commit()

        # The memory that spelled him "Dave Smith" is the one being pulled out.
        moving = [
            m
            for m in await _mentions(test_db, dave)
            if m.surface_form == "Dave Smith"
        ]
        split = await split_entity(
            test_db,
            str(user.id),
            str(dave.id),
            [str(moving[0].id)],
            "Dave Smith",
        )
        await test_db.commit()

        # "dave smith" went with the memory; "dave" is still in use here.
        assert (
            await find_entity_by_alias(test_db, str(user.id), "person", "dave smith")
        ).id == split.new_entity_id
        assert (
            await find_entity_by_alias(test_db, str(user.id), "person", "dave")
        ).id == dave.id

    @pytest.mark.asyncio
    async def test_a_split_can_be_undone(self, test_db, user):
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "two")
        dave = await _entity(test_db, "Dave")
        new_entity_id = None

        split = await split_entity(
            test_db,
            str(user.id),
            str(dave.id),
            [str(m.id) for m in await _mentions(test_db, dave)][:1],
            "Dave Smith",
        )
        new_entity_id = split.new_entity_id
        await test_db.commit()

        await undo_split(test_db, str(user.id), str(split.id))
        await test_db.commit()

        assert len(await _mentions(test_db, dave)) == 2
        # The new entity only existed because of the split.
        assert await test_db.get(Entity, new_entity_id) is None

    @pytest.mark.asyncio
    async def test_another_user_cannot_split(self, test_db, user):
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        dave = await _entity(test_db, "Dave")
        mention = (await _mentions(test_db, dave))[0]

        stranger = User(username="bob", email="bob@example.com", password_hash="h")
        test_db.add(stranger)
        await test_db.commit()
        await test_db.refresh(stranger)

        with pytest.raises(ValueError):
            await split_entity(
                test_db,
                str(stranger.id),
                str(dave.id),
                [str(mention.id)],
                "Dave Smith",
            )

    @pytest.mark.asyncio
    async def test_a_nameless_or_emptied_split_is_refused(self, test_db, user):
        await _memory_with(test_db, user.id, [("person", "Dave", None)], "one")
        dave = await _entity(test_db, "Dave")
        mention = (await _mentions(test_db, dave))[0]

        with pytest.raises(ValueError):
            await split_entity(
                test_db, str(user.id), str(dave.id), [str(mention.id)], "   "
            )
        with pytest.raises(ValueError):
            await split_entity(test_db, str(user.id), str(dave.id), [], "Dave Smith")
