"""Tests for derived related memories.

"Related" means memories that share first-class entities (people, places,
organizations). This replaces the old stored ``related_memory_ids`` list, which
the enrichment agent was supposed to fill but which stayed empty because it
depended on embeddings that older memories never got.

Deriving on read from entity mentions is deterministic, works retroactively,
never goes stale, and is explainable ("3 shared people").
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone, timedelta

from app.main import app
from app.db import Base, User, Memory, get_db
from app.db.entities import sync_memory_entities, find_related_memories
from app.security import hash_password


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
def client(test_db):
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def setup_users(test_db):
    async def _setup():
        user1 = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        user2 = User(
            username="bob",
            email="bob@example.com",
            password_hash=hash_password("password456"),
        )
        test_db.add(user1)
        test_db.add(user2)
        await test_db.commit()
        await test_db.refresh(user1)
        await test_db.refresh(user2)
        return user1, user2

    return _setup


@pytest.fixture
def get_auth_token(client):
    def _get_token(username: str, password: str):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return response.json()["access_token"]

    return _get_token


async def _seed(
    session,
    user_id,
    entities,
    title="memory",
    is_private=False,
    event_date=None,
):
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
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        is_private=is_private,
        event_date=event_date or datetime(2024, 5, 1, tzinfo=timezone.utc),
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    await sync_memory_entities(session, str(user_id), str(memory.id), content)
    await session.commit()
    return memory


class TestFindRelatedMemories:
    """Service-level behaviour."""

    @pytest.mark.asyncio
    async def test_memories_sharing_a_person_are_related(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        other = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "b")

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert [str(memory.id) for memory, _, _ in related] == [str(other.id)]

    @pytest.mark.asyncio
    async def test_unrelated_memories_are_excluded(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        await _seed(test_db, str(user1.id), [("person", "Sarah", None)], "b")

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert related == []

    @pytest.mark.asyncio
    async def test_ranked_by_number_of_shared_entities(self, test_db, setup_users):
        """A memory sharing two entities outranks one sharing a single entity."""
        user1, _ = await setup_users()
        target = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "target",
        )
        one_shared = await _seed(
            test_db, str(user1.id), [("person", "Mike", None)], "one"
        )
        two_shared = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "two",
        )

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert [str(memory.id) for memory, _, _ in related] == [
            str(two_shared.id),
            str(one_shared.id),
        ]
        assert related[0][2] == 2  # shared entity count
        assert related[1][2] == 1

    @pytest.mark.asyncio
    async def test_shares_entities_not_just_copies(self, test_db, setup_users):
        """A different surface form of the same entity still links."""
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Sarah", None)], "a")
        other = await _seed(
            test_db, str(user1.id), [("person", "Sarah's", None)], "b"
        )

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert [str(m.id) for m, _, _ in related] == [str(other.id)]

    @pytest.mark.asyncio
    async def test_self_is_never_included(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert all(str(m.id) != str(target.id) for m, _, _ in related)

    @pytest.mark.asyncio
    async def test_scoped_to_user(self, test_db, setup_users):
        user1, user2 = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        await _seed(test_db, str(user2.id), [("person", "Mike", None)], "b")

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert related == []

    @pytest.mark.asyncio
    async def test_shared_entity_names_are_returned(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "a",
        )
        await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "b",
        )

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        _, shared, _ = related[0]
        assert sorted(shared) == ["Denver", "Mike"]

    @pytest.mark.asyncio
    async def test_respects_the_limit(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "t")
        for i in range(5):
            await _seed(test_db, str(user1.id), [("person", "Mike", None)], f"m{i}")

        related = await find_related_memories(
            test_db, str(user1.id), str(target.id), limit=2
        )

        assert len(related) == 2


class TestRelatedMemoriesPrivacy:
    """Locked memories must not surface as related."""

    @pytest.mark.asyncio
    async def test_locked_related_memory_is_hidden(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None)],
            "secret",
            is_private=True,
        )

        related = await find_related_memories(test_db, str(user1.id), str(target.id))

        assert related == []

    @pytest.mark.asyncio
    async def test_unlocking_reveals_the_related_memory(self, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        secrets = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None)],
            "secret",
            is_private=True,
        )

        related = await find_related_memories(
            test_db, str(user1.id), str(target.id), unlocked_ids=[str(secrets.id)]
        )

        assert [str(m.id) for m, _, _ in related] == [str(secrets.id)]


class TestRelatedEndpoint:
    """GET /api/memories/{id}/related"""

    @pytest.mark.asyncio
    async def test_returns_related_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        target = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "target",
        )
        other = await _seed(
            test_db,
            str(user1.id),
            [("person", "Mike", None), ("place", "Denver", None)],
            "other",
        )

        response = client.get(
            f"/api/memories/{target.id}/related",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == str(other.id)
        assert sorted(item["shared_entities"]) == ["Denver", "Mike"]
        assert item["shared_count"] == 2

    @pytest.mark.asyncio
    async def test_404_for_other_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        target = await _seed(test_db, str(user2.id), [("person", "Mike", None)], "b")

        response = client.get(
            f"/api/memories/{target.id}/related",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_source_is_locked(
        self, client, test_db, setup_users, get_auth_token
    ):
        """A locked memory's relationships must not be discoverable."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        target = await _seed(
            test_db, str(user1.id), [("person", "Mike", None)], "secret", is_private=True
        )
        await _seed(test_db, str(user1.id), [("person", "Mike", None)], "public")

        response = client.get(
            f"/api/memories/{target.id}/related",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_locked_related_memory_hidden_from_response(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")
        await _seed(
            test_db, str(user1.id), [("person", "Mike", None)], "secret", is_private=True
        )

        response = client.get(
            f"/api/memories/{target.id}/related",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["items"] == []

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client, test_db, setup_users):
        user1, _ = await setup_users()
        target = await _seed(test_db, str(user1.id), [("person", "Mike", None)], "a")

        response = client.get(f"/api/memories/{target.id}/related")

        assert response.status_code in (401, 403)
