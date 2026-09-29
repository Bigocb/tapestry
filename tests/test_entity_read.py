"""Tests for the entity read path (people/places/organizations API).

The central privacy rule: an entity is visible only if the user has at least
one **non-locked** memory mentioning it. A person who appears exclusively in
locked memories must not leak into lists or counts.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.main import app
from app.db import Base, User, Memory, get_db
from app.db.entities import sync_memory_entities
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


async def _seed_memory(
    session,
    user_id,
    entities,
    title="memory",
    is_private=False,
    event_date=None,
):
    """Create a memory with the given entity mentions and sync them."""
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


class TestEntityList:
    """GET /api/entities"""

    @pytest.mark.asyncio
    async def test_lists_people_and_places(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "Sarah", None), ("place", "Denver", None)],
        )

        response = client.get(
            "/api/entities", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        names = {item["canonical_name"] for item in data["items"]}
        assert names == {"Sarah", "Denver"}
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_filters_by_kind(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "Sarah", None), ("place", "Denver", None)],
        )

        response = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        names = [item["canonical_name"] for item in response.json()["items"]]
        assert names == ["Sarah"]

    @pytest.mark.asyncio
    async def test_mention_count_reflects_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), [("person", "Sarah", None)])
        await _seed_memory(test_db, str(user1.id), [("person", "Sarah", None)])

        response = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        )

        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["mention_count"] == 2

    @pytest.mark.asyncio
    async def test_ordered_by_mention_count_desc(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), [("person", "Rare", None)])
        await _seed_memory(test_db, str(user1.id), [("person", "Often", None)])
        await _seed_memory(test_db, str(user1.id), [("person", "Often", None)])

        response = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        )

        names = [item["canonical_name"] for item in response.json()["items"]]
        assert names == ["Often", "Rare"]

    @pytest.mark.asyncio
    async def test_scoped_to_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), [("person", "Mine", None)])
        await _seed_memory(test_db, str(user2.id), [("person", "Theirs", None)])

        response = client.get(
            "/api/entities", headers={"Authorization": f"Bearer {token}"}
        )

        names = [item["canonical_name"] for item in response.json()["items"]]
        assert names == ["Mine"]

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        assert client.get("/api/entities").status_code in (401, 403)


class TestEntityPrivacy:
    """Locked memories must not leak entities or inflate counts."""

    @pytest.mark.asyncio
    async def test_entity_only_in_locked_memories_is_hidden(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "SecretFriend", None)],
            is_private=True,
        )
        await _seed_memory(test_db, str(user1.id), [("person", "PublicFriend", None)])

        response = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        )

        names = [item["canonical_name"] for item in response.json()["items"]]
        assert names == ["PublicFriend"]
        assert "SecretFriend" not in response.text

    @pytest.mark.asyncio
    async def test_count_excludes_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        """Sarah is in 1 public and 1 locked memory; the count must be 1."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), [("person", "Sarah", None)])
        await _seed_memory(
            test_db, str(user1.id), [("person", "Sarah", None)], is_private=True
        )

        response = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        )

        items = response.json()["items"]
        assert items[0]["mention_count"] == 1

    @pytest.mark.asyncio
    async def test_unlocking_reveals_the_entity(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "SecretFriend", None)],
            is_private=True,
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Unlocked-Memory-Ids": str(memory.id),
        }
        response = client.get("/api/entities?kind=person", headers=headers)

        names = [item["canonical_name"] for item in response.json()["items"]]
        assert names == ["SecretFriend"]


class TestEntityDetail:
    """GET /api/entities/{id}"""

    @pytest.mark.asyncio
    async def test_detail_includes_aliases_and_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db, str(user1.id), [("person", "Dawn", {"relation": "wife"})]
        )

        listing = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        entity_id = listing["items"][0]["id"]

        response = client.get(
            f"/api/entities/{entity_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["canonical_name"] == "Dawn"
        assert data["kind"] == "person"
        assert "dawn" in [a.lower() for a in data["aliases"]]
        assert len(data["memories"]) == 1
        assert str(memory.id) in [m["id"] for m in data["memories"]]

    @pytest.mark.asyncio
    async def test_detail_hides_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), [("person", "Sarah", None)])
        await _seed_memory(
            test_db, str(user1.id), [("person", "Sarah", None)], is_private=True
        )

        listing = client.get(
            "/api/entities?kind=person",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        entity_id = listing["items"][0]["id"]

        response = client.get(
            f"/api/entities/{entity_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert len(response.json()["memories"]) == 1

    @pytest.mark.asyncio
    async def test_detail_404_when_only_locked(
        self, client, test_db, setup_users, get_auth_token
    ):
        """An entity visible nowhere must not be reachable, even by id."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "SecretFriend", None)],
            is_private=True,
        )

        # Grab the id directly from the DB to bypass the (hidden) listing.
        from app.db import Entity
        from sqlalchemy import select

        entity = (
            await test_db.execute(select(Entity).where(Entity.canonical_name == "SecretFriend"))
        ).scalars().one()

        response = client.get(
            f"/api/entities/{entity.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_detail_404_for_other_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user2.id), [("person", "BobPerson", None)])

        from app.db import Entity
        from sqlalchemy import select

        entity = (
            await test_db.execute(select(Entity).where(Entity.canonical_name == "BobPerson"))
        ).scalars().one()

        response = client.get(
            f"/api/entities/{entity.id}",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404


class TestEntityCounts:
    """GET /api/entities/counts for nav badges."""

    @pytest.mark.asyncio
    async def test_counts_by_kind(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "Sarah", None), ("place", "Denver", None)],
        )
        await _seed_memory(test_db, str(user1.id), [("person", "Mike", None)])

        response = client.get(
            "/api/entities/counts",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["person"] == 2
        assert data["place"] == 1

    @pytest.mark.asyncio
    async def test_counts_exclude_locked_only_entities(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            [("person", "SecretFriend", None)],
            is_private=True,
        )

        response = client.get(
            "/api/entities/counts",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.json()["person"] == 0
