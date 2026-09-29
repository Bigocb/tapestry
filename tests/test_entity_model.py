"""Tests for the first-class entity model (people, places, organizations).

Entities are split into three concepts:
- Entity      : the canonical thing (one row per real person/place/org)
- EntityAlias : every way its name has been written
- MemoryEntity: one mention of an entity inside one memory

Only *exact* normalized name matches auto-link. Fuzzy matches (initials,
partials) are never merged automatically.
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
    apply_mentions,
    normalize_name,
    find_entity_by_alias,
    entity_ids_for_memory,
    recompute_entity_stats,
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
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="hashed",
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def _make_memory(session, user_id, text="some memory", **kwargs):
    memory = Memory(
        raw_input=text,
        input_type="text",
        user_id=user_id,
        structured_content={"title": text[:40], "summary": text},
        tags=[],
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        **kwargs,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestNormalizeName:
    """Name normalization is the matching key, so it must be predictable."""

    def test_lowercases_and_trims(self):
        assert normalize_name("  Sarah Smith  ") == "sarah smith"

    def test_collapses_internal_whitespace(self):
        assert normalize_name("Sarah   Smith") == "sarah smith"

    def test_strips_trailing_possessive(self):
        assert normalize_name("Sarah's") == "sarah"
        assert normalize_name("Sarah'") == "sarah"

    def test_plural_possessive_loses_only_the_apostrophe(self):
        # "the Sarahs'" refers to a family by surname; the base is "Sarahs".
        assert normalize_name("Sarahs'") == "sarahs"

    def test_strips_surrounding_punctuation(self):
        assert normalize_name("Sarah.") == "sarah"
        assert normalize_name("(Sarah)") == "sarah"

    def test_preserves_hyphens_and_apostrophes_inside_names(self):
        assert normalize_name("Anne-Marie") == "anne-marie"
        assert normalize_name("O'Brien") == "o'brien"

    def test_empty_is_empty(self):
        assert normalize_name("   ") == ""


class TestExactAliasAutoLink:
    """The same written name must resolve to the same entity."""

    @pytest.mark.asyncio
    async def test_two_memories_sharing_a_name_share_one_entity(
        self, test_db, user
    ):
        m1 = await _make_memory(test_db, str(user.id), "coffee with Sarah")
        m2 = await _make_memory(test_db, str(user.id), "Sarah called me")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah", None)]
        )

        result = await test_db.execute(
            select(Entity).where(Entity.kind == "person")
        )
        entities = result.scalars().all()
        assert len(entities) == 1
        assert entities[0].canonical_name == "Sarah"
        assert entities[0].mention_count == 2

    @pytest.mark.asyncio
    async def test_case_and_punctuation_variants_link(self, test_db, user):
        m1 = await _make_memory(test_db, str(user.id), "sarah")
        m2 = await _make_memory(test_db, str(user.id), "SARAH.")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "SARAH.", None)]
        )

        result = await test_db.execute(select(Entity))
        assert len(result.scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_alias_is_recorded_per_spelling(self, test_db, user):
        m1 = await _make_memory(test_db, str(user.id), "Sarah")
        m2 = await _make_memory(test_db, str(user.id), "Sarah's birthday")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah's", None)]
        )

        result = await test_db.execute(select(EntityAlias))
        aliases = {a.normalized_alias for a in result.scalars().all()}
        # Both spellings normalize to "sarah", so one alias row suffices.
        assert aliases == {"sarah"}

    @pytest.mark.asyncio
    async def test_full_name_is_a_distinct_entity_from_first_name(
        self, test_db, user
    ):
        """Exact-only linking means 'Sarah' and 'Sarah Smith' stay separate.

        They may be the same person, but merging them is the user's call.
        """
        m1 = await _make_memory(test_db, str(user.id), "Sarah")
        m2 = await _make_memory(test_db, str(user.id), "Sarah Smith")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah Smith", None)]
        )

        result = await test_db.execute(select(Entity))
        entities = result.scalars().all()
        assert len(entities) == 2
        assert {e.canonical_name for e in entities} == {"Sarah", "Sarah Smith"}


class TestKinds:
    """Only person, place and organization become first-class."""

    @pytest.mark.asyncio
    async def test_place_becomes_an_entity(self, test_db, user):
        m = await _make_memory(test_db, str(user.id), "trip to Denver")
        await apply_mentions(
            test_db, str(user.id), str(m.id), [("place", "Denver", None)]
        )

        result = await test_db.execute(select(Entity).where(Entity.kind == "place"))
        entities = result.scalars().all()
        assert len(entities) == 1
        assert entities[0].canonical_name == "Denver"

    @pytest.mark.asyncio
    async def test_date_and_event_are_ignored(self, test_db, user):
        """Dates are handled by event_date; event/concept stay as JSON."""
        m = await _make_memory(test_db, str(user.id), "July 1976")
        await apply_mentions(
            test_db,
            str(user.id),
            str(m.id),
            [
                ("date", "July 1976", None),
                ("event", "the wedding", None),
                ("concept", "grief", None),
            ],
        )

        result = await test_db.execute(select(Entity))
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_person_and_place_with_same_name_do_not_collide(
        self, test_db, user
    ):
        """Kind is part of identity: a person named Paris != the city Paris."""
        m1 = await _make_memory(test_db, str(user.id), "Paris called")
        m2 = await _make_memory(test_db, str(user.id), "went to Paris")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Paris", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("place", "Paris", None)]
        )

        result = await test_db.execute(select(Entity))
        assert len(result.scalars().all()) == 2


class TestMentions:
    """Mentions connect an entity to a memory."""

    @pytest.mark.asyncio
    async def test_mention_records_surface_form_and_role(self, test_db, user):
        m = await _make_memory(test_db, str(user.id), "Dawn and I")
        await apply_mentions(
            test_db, str(user.id), str(m.id), [("person", "Dawn", "wife")]
        )

        result = await test_db.execute(select(MemoryEntity))
        mentions = result.scalars().all()
        assert len(mentions) == 1
        assert mentions[0].surface_form == "Dawn"
        assert mentions[0].role == "wife"
        assert str(mentions[0].memory_id) == str(m.id)

    @pytest.mark.asyncio
    async def test_reapplying_same_mention_is_idempotent(self, test_db, user):
        """Recapture/reprocessing must not duplicate mentions."""
        m = await _make_memory(test_db, str(user.id), "Sarah")
        await apply_mentions(
            test_db, str(user.id), str(m.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m.id), [("person", "Sarah", None)]
        )

        result = await test_db.execute(select(MemoryEntity))
        assert len(result.scalars().all()) == 1


class TestIdTypeConsistency:
    """Regression: ids must be one Python type within a session.

    The GUID column default previously produced a str while the result
    processor returned a UUID, so a created row and a loaded row had different
    id types for the same value. SQLAlchemy's flush ordering then compared
    UUID < str and raised InvalidRequestError. The entity backfill was the
    first code to create-then-query in one session, so it crashed on startup.
    """

    @pytest.mark.asyncio
    async def test_created_and_loaded_ids_share_a_type(self, test_db, user):
        m1 = await _make_memory(test_db, str(user.id), "a")
        m2 = await _make_memory(test_db, str(user.id), "b")

        created = await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        created_id = created[0].id

        loaded = await find_entity_by_alias(test_db, str(user.id), "person", "sarah")
        assert loaded is not None
        assert type(loaded.id) is type(created_id)

        # Create + query + update in one flush must not raise
        # "primary key values must be sortable".
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah", None)]
        )
        await test_db.commit()


class TestMentionCountAndTimestamps:
    """Denormalized counters must stay accurate."""

    @pytest.mark.asyncio
    async def test_count_and_seen_window_track_mentions(self, test_db, user):
        m1 = await _make_memory(test_db, str(user.id), "a")
        m2 = await _make_memory(test_db, str(user.id), "b")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah", None)]
        )

        result = await test_db.execute(select(Entity))
        entity = result.scalars().one()
        assert entity.mention_count == 2
        assert entity.first_seen_at is not None
        assert entity.last_seen_at is not None

    @pytest.mark.asyncio
    async def test_removing_a_memory_lowers_the_count(self, test_db, user):
        """Deleting a memory must not leave a stale, inflated mention count.

        The DELETE route captures the affected entity ids, deletes the memory,
        then recomputes stats. This mirrors that sequence.
        """
        m1 = await _make_memory(test_db, str(user.id), "a")
        m2 = await _make_memory(test_db, str(user.id), "b")
        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(user.id), str(m2.id), [("person", "Sarah", None)]
        )

        affected = await entity_ids_for_memory(test_db, str(m2.id))
        await test_db.delete(m2)
        await test_db.commit()
        await recompute_entity_stats(test_db, affected)
        await test_db.commit()

        result = await test_db.execute(select(Entity))
        entity = result.scalars().one()
        assert entity.mention_count == 1


class TestUserIsolation:
    """Entities never leak across users."""

    @pytest.mark.asyncio
    async def test_same_name_different_users_are_separate_entities(
        self, test_db, user
    ):
        other = User(username="bob", email="bob@example.com", password_hash="x")
        test_db.add(other)
        await test_db.commit()
        await test_db.refresh(other)

        m1 = await _make_memory(test_db, str(user.id), "Sarah")
        m2 = await _make_memory(test_db, str(other.id), "Sarah")

        await apply_mentions(
            test_db, str(user.id), str(m1.id), [("person", "Sarah", None)]
        )
        await apply_mentions(
            test_db, str(other.id), str(m2.id), [("person", "Sarah", None)]
        )

        result = await test_db.execute(select(Entity))
        assert len(result.scalars().all()) == 2

    @pytest.mark.asyncio
    async def test_lookup_is_scoped_to_user(self, test_db, user):
        other = User(username="bob2", email="bob2@example.com", password_hash="x")
        test_db.add(other)
        await test_db.commit()
        await test_db.refresh(other)

        m = await _make_memory(test_db, str(user.id), "Sarah")
        await apply_mentions(
            test_db, str(user.id), str(m.id), [("person", "Sarah", None)]
        )

        # Different user must not resolve to alice's entity.
        found = await find_entity_by_alias(test_db, str(other.id), "person", "sarah")
        assert found is None
