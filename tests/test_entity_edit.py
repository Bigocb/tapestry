"""Tests for editing an entity by hand: name, description, address.

A place read out of a memory is a guess. The user knows what the place is
called and where it is, so the card has to be correctable — and correcting the
name must not orphan the name it was extracted under.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, Memory, User, get_db
from app.db.entities import normalize_name, sync_memory_entities
from app.db.models import Entity
from app.security import hash_password


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        TEST_DATABASE_URL, echo=False, poolclass=StaticPool
    )
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
        alice = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        bob = User(
            username="bob",
            email="bob@example.com",
            password_hash=hash_password("password456"),
        )
        test_db.add(alice)
        test_db.add(bob)
        await test_db.commit()
        await test_db.refresh(alice)
        await test_db.refresh(bob)
        return alice, bob

    return _setup


@pytest.fixture
def get_auth_token(client):
    def _get(username: str, password: str):
        return client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        ).json()["access_token"]

    return _get


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _mentioning(session, user_id, kind, name):
    content = {
        "title": name,
        "summary": name,
        "entities": [{"type": kind, "value": name, "metadata": None}],
    }
    memory = Memory(
        raw_input=name,
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

    result = await session.execute(
        select(Entity).where(
            Entity.canonical_name == name, Entity.kind == kind
        )
    )
    return str(result.scalars().first().id)


class TestRenameAPlace:
    """A place's name is the user's to correct."""

    @pytest.mark.asyncio
    async def test_a_place_can_be_renamed(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"canonical_name": "Mission Valley Cinemas"},
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert response.json()["canonical_name"] == "Mission Valley Cinemas"

    @pytest.mark.asyncio
    async def test_the_old_name_is_kept_as_an_alias(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"canonical_name": "Mission Valley Cinemas"},
            headers=_auth(token),
        )

        # The memories still say "Theater"; that spelling must still resolve here.
        assert "Mission Valley Theater" in response.json()["aliases"]

    @pytest.mark.asyncio
    async def test_the_matching_key_follows_the_new_name(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Blueburd Cafe")

        client.patch(
            f"/api/entities/{entity_id}",
            json={"canonical_name": "Bluebird Cafe"},
            headers=_auth(token),
        )

        result = await test_db.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        stored = result.scalars().first()
        assert stored.normalized_name == normalize_name("Bluebird Cafe")

    @pytest.mark.asyncio
    async def test_a_blank_name_is_refused(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Nonna's")

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"canonical_name": "   "},
            headers=_auth(token),
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_renaming_onto_another_place_is_refused(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        first = await _mentioning(test_db, user.id, "place", "Bluebird Cafe")
        await _mentioning(test_db, user.id, "place", "Nonna's")

        response = client.patch(
            f"/api/entities/{first}",
            json={"canonical_name": "Nonna's"},
            headers=_auth(token),
        )

        # Merging is the way to make two entities one, and it is reversible.
        assert response.status_code == 409


class TestDescriptionAndAddress:
    """The rest of the card: what it is, and where."""

    @pytest.mark.asyncio
    async def test_a_description_can_be_set(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "The Hollow")

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"description": "Dive bar where trivia night happens"},
            headers=_auth(token),
        )

        assert response.json()["description"] == (
            "Dive bar where trivia night happens"
        )

    @pytest.mark.asyncio
    async def test_a_description_can_be_cleared(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "The Hollow")
        client.patch(
            f"/api/entities/{entity_id}",
            json={"description": "Somewhere"},
            headers=_auth(token),
        )

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"description": None},
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert response.json()["description"] is None

    @pytest.mark.asyncio
    async def test_an_address_can_be_set_on_a_place(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Nonna's")

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"address": "1201 Larimer St, Denver, CO 80204"},
            headers=_auth(token),
        )

        assert response.json()["attributes"]["address"] == (
            "1201 Larimer St, Denver, CO 80204"
        )

    @pytest.mark.asyncio
    async def test_an_address_can_be_cleared(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Nonna's")
        client.patch(
            f"/api/entities/{entity_id}",
            json={"address": "1201 Larimer St, Denver, CO 80204"},
            headers=_auth(token),
        )

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"address": None},
            headers=_auth(token),
        )

        assert response.status_code == 200
        attributes = response.json()["attributes"] or {}
        assert "address" not in attributes

    @pytest.mark.asyncio
    async def test_other_attributes_survive_an_address_edit(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Nonna's")

        result = await test_db.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        stored = result.scalars().first()
        stored.attributes = {"parent": "Denver"}
        await test_db.commit()

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"address": "1201 Larimer St, Denver, CO 80204"},
            headers=_auth(token),
        )

        attributes = response.json()["attributes"]
        assert attributes["parent"] == "Denver"
        assert attributes["address"] == "1201 Larimer St, Denver, CO 80204"

    @pytest.mark.asyncio
    async def test_an_address_is_refused_for_a_person(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "person", "Sarah")

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"address": "1201 Larimer St"},
            headers=_auth(token),
        )

        assert response.status_code == 400


class TestScoping:
    """An edit must only reach the user's own entity."""

    @pytest.mark.asyncio
    async def test_an_unrelated_field_is_untouched(
        self, client, setup_users, get_auth_token, test_db
    ):
        user, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "place", "Nonna's")
        client.patch(
            f"/api/entities/{entity_id}",
            json={"description": "Kept", "address": "Somewhere"},
            headers=_auth(token),
        )

        response = client.patch(
            f"/api/entities/{entity_id}",
            json={"canonical_name": "Nonna's Kitchen"},
            headers=_auth(token),
        )

        body = response.json()
        assert body["description"] == "Kept"
        assert body["attributes"]["address"] == "Somewhere"

    @pytest.mark.asyncio
    async def test_another_users_entity_cannot_be_edited(
        self, client, setup_users, get_auth_token, test_db
    ):
        alice, bob = await setup_users()
        alice_token = get_auth_token("alice", "password123")
        bob_token = get_auth_token("bob", "password456")
        bobs_place = await _mentioning(test_db, bob.id, "place", "Bob's Bar")

        response = client.patch(
            f"/api/entities/{bobs_place}",
            json={"canonical_name": "Mine Now"},
            headers=_auth(alice_token),
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_an_unknown_entity_is_404(
        self, client, setup_users, get_auth_token
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.patch(
            "/api/entities/00000000-0000-0000-0000-000000000000",
            json={"canonical_name": "Nowhere"},
            headers=_auth(token),
        )

        assert response.status_code == 404
