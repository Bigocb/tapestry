"""Tests for looking a place up and keeping the result (Issue 38).

Provenance is the whole point. A fact found outside the app must never be
mistaken for something the user said, so it is stored apart and labelled with
where it came from and when.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, Memory, User, get_db
from app.db.entities import sync_memory_entities
from app.db.models import Entity
from app.lookup import PlaceMatch
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
        return alice

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


CINEMA = PlaceMatch(
    source="wikidata",
    source_id="Q43096397",
    label="Mission Valley Cinemas",
    description="movie theater in Raleigh, North Carolina, United States",
    url="http://www.wikidata.org/entity/Q43096397",
)


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


class TestLookupCandidates:
    """Looking up offers choices, and never looks up a person."""

    @pytest.mark.asyncio
    async def test_a_place_lookup_offers_candidates(
        self, client, setup_users, get_auth_token, test_db, monkeypatch
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )

        async def fake_search(name, limit=3):
            return [CINEMA]

        monkeypatch.setattr("app.routes.entities.search_places", fake_search)

        response = client.get(
            f"/api/entities/{entity_id}/lookup", headers=_auth(token)
        )

        assert response.status_code == 200
        candidates = response.json()
        # What was matched travels with it, or a wrong match is invisible.
        assert candidates[0]["label"] == "Mission Valley Cinemas"
        assert candidates[0]["description"].startswith("movie theater in Raleigh")
        assert candidates[0]["source_id"] == "Q43096397"

    @pytest.mark.asyncio
    async def test_a_place_that_finds_nothing_answers_with_nothing(
        self, client, setup_users, get_auth_token, test_db, monkeypatch
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "A Place That Never Was"
        )

        async def fake_search(name, limit=3):
            return []

        monkeypatch.setattr("app.routes.entities.search_places", fake_search)

        response = client.get(
            f"/api/entities/{entity_id}/lookup", headers=_auth(token)
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_a_person_is_never_looked_up(
        self, client, setup_users, get_auth_token, test_db, monkeypatch
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(test_db, user.id, "person", "Dave")

        asked: list[str] = []

        async def fake_search(name, limit=3):
            asked.append(name)
            return [CINEMA]

        monkeypatch.setattr("app.routes.entities.search_places", fake_search)

        response = client.get(
            f"/api/entities/{entity_id}/lookup", headers=_auth(token)
        )

        # Identifying a real person from a first name is unreliable and
        # invasive, so it is refused rather than attempted.
        assert response.status_code == 400
        assert asked == []


class TestKeptFacts:
    """A fact is stored apart, labelled, and can be thrown away."""

    @pytest.mark.asyncio
    async def test_keeping_a_candidate_records_where_it_came_from(
        self, client, setup_users, get_auth_token, test_db
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )

        response = client.post(
            f"/api/entities/{entity_id}/facts",
            json={
                "source": CINEMA.source,
                "source_id": CINEMA.source_id,
                "label": CINEMA.label,
                "description": CINEMA.description,
                "url": CINEMA.url,
            },
            headers=_auth(token),
        )

        assert response.status_code == 201
        fact = response.json()
        assert fact["source"] == "wikidata"
        assert fact["source_id"] == "Q43096397"
        assert fact["fetched_at"]

        detail = client.get(
            f"/api/entities/{entity_id}", headers=_auth(token)
        ).json()
        assert [f["label"] for f in detail["facts"]] == ["Mission Valley Cinemas"]

    @pytest.mark.asyncio
    async def test_a_fact_can_be_discarded(
        self, client, setup_users, get_auth_token, test_db
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )
        fact_id = client.post(
            f"/api/entities/{entity_id}/facts",
            json={
                "source": CINEMA.source,
                "source_id": CINEMA.source_id,
                "label": CINEMA.label,
                "description": CINEMA.description,
                "url": CINEMA.url,
            },
            headers=_auth(token),
        ).json()["id"]

        response = client.delete(
            f"/api/entities/{entity_id}/facts/{fact_id}", headers=_auth(token)
        )

        assert response.status_code == 204
        detail = client.get(
            f"/api/entities/{entity_id}", headers=_auth(token)
        ).json()
        assert detail["facts"] == []

    @pytest.mark.asyncio
    async def test_another_user_cannot_look_up_or_keep_facts(
        self, client, setup_users, get_auth_token, test_db, monkeypatch
    ):
        user = await setup_users()
        alice = get_auth_token("alice", "password123")
        bob = get_auth_token("bob", "password456")
        entity_id = await _mentioning(
            test_db, user.id, "place", "Mission Valley Theater"
        )

        assert (
            client.get(
                f"/api/entities/{entity_id}/lookup", headers=_auth(bob)
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/entities/{entity_id}/facts",
                json={
                    "source": "wikidata",
                    "source_id": "Q43096397",
                    "label": "Mission Valley Cinemas",
                    "description": None,
                    "url": "http://x",
                },
                headers=_auth(bob),
            ).status_code
            == 404
        )
