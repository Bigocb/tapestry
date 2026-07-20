"""Tests for hybrid memory search."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, Memory, get_db
from app.security import hash_password
from app.models.schemas import SearchFilters, StructuredMemory


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
        user = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        test_db.add(user)
        await test_db.commit()
        await test_db.refresh(user)
        return user

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


@pytest.fixture
def fake_generate_embedding(monkeypatch):
    """Return deterministic embeddings based on text content so tests are stable."""

    async def _fake(text: str):
        from app.agents.embeddings import _fallback_embedding

        return _fallback_embedding(text)

    monkeypatch.setattr("app.jobs.worker.generate_embedding", _fake)


@pytest.fixture
def fake_structure_memory(monkeypatch):
    async def _fake(raw_input: str):
        return StructuredMemory(
            title=raw_input[:50],
            summary=raw_input,
            entities=[],
            mood="neutral",
            importance_level=5,
            initial_tags=["test"],
        )

    monkeypatch.setattr("app.routes.memories.structure_memory", _fake)


async def _seed_memory(
    session,
    user_id: str,
    raw_input: str,
    title: str,
    tags: list[str],
    mood: str,
    importance_level: int,
    embedding: list[float] | None = None,
):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
        tags=tags,
        mood=mood,
        importance_level=importance_level,
        processing_state="enriched",
        related_memory_ids=[],
    )
    if embedding:
        import json as _json

        memory.embedding = _json.dumps(embedding)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestHybridSearchEndpoint:
    """Test POST /api/memories/search hybrid endpoint."""

    @pytest.mark.asyncio
    async def test_hybrid_search_by_full_text(
        self, client, test_db, setup_users, get_auth_token, fake_generate_embedding
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user.id), "coffee with Sarah", "Coffee", ["social"], "happy", 6)
        await _seed_memory(test_db, str(user.id), "project meeting with team", "Meeting", ["work"], "focused", 7)
        await _seed_memory(test_db, str(user.id), "gym session", "Gym", ["health"], "tired", 4)

        response = client.post(
            "/api/memories/search",
            json={"text": "coffee Sarah", "limit": 10},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["title"] == "Coffee"

    @pytest.mark.asyncio
    async def test_hybrid_search_by_filters_only(
        self, client, test_db, setup_users, get_auth_token, fake_generate_embedding
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user.id), "ran a marathon", "Marathon", ["health"], "proud", 9)
        await _seed_memory(test_db, str(user.id), "watched a movie", "Movie", ["social"], "happy", 5)

        response = client.post(
            "/api/memories/search",
            json={
                "filters": {"tags": ["health"]},
                "limit": 10,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["results"][0]["title"] == "Marathon"

    @pytest.mark.asyncio
    async def test_hybrid_search_respects_user_isolation(
        self, client, test_db, setup_users, get_auth_token, fake_generate_embedding
    ):
        user1 = await setup_users()
        user2 = User(
            username="bob",
            email="bob@example.com",
            password_hash=hash_password("password456"),
        )
        test_db.add(user2)
        await test_db.commit()
        await test_db.refresh(user2)

        token1 = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "alice private note", "Alice", ["private"], "calm", 5)
        await _seed_memory(test_db, str(user2.id), "bob private note", "Bob", ["private"], "calm", 5)

        response = client.post(
            "/api/memories/search",
            json={"text": "private", "limit": 10},
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["results"][0]["title"] == "Alice"

    @pytest.mark.asyncio
    async def test_hybrid_search_pagination(
        self, client, test_db, setup_users, get_auth_token, fake_generate_embedding
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")

        for i in range(5):
            await _seed_memory(
                test_db,
                str(user.id),
                f"memory number {i} about coffee",
                f"Memory {i}",
                ["coffee"],
                "happy",
                5,
            )

        response = client.post(
            "/api/memories/search",
            json={"text": "coffee", "limit": 2, "offset": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["results"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 1



