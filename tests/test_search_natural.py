"""Tests for natural language search endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, Memory, get_db
from app.security import hash_password
from app.models.schemas import StructuredMemory


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
    async def _fake(text: str):
        from app.agents.embeddings import _fallback_embedding
        return _fallback_embedding(text)

    monkeypatch.setattr("app.routes.memories.generate_embedding", _fake)


@pytest.fixture
def fake_parse_search_query(monkeypatch):
    """Mock the Search Agent to return a predictable structured query."""
    from app.models.schemas import SearchFilters, SearchQuery

    async def _fake(query: str):
        return SearchQuery(
            text="coffee",
            semantic="casual meetings",
            filters=SearchFilters(tags=["social"]),
            limit=10,
            offset=0,
        )

    monkeypatch.setattr("app.routes.memories.parse_search_query", _fake)


async def _seed_memory(session, user_id, raw_input, title, tags, mood, importance_level):
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
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestNaturalLanguageSearchEndpoint:
    """Test POST /api/memories/search/natural."""

    @pytest.mark.asyncio
    async def test_natural_search_parses_and_searches(
        self, client, test_db, setup_users, get_auth_token, fake_generate_embedding, fake_parse_search_query
    ):
        user = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user.id), "coffee with Sarah", "Coffee", ["social"], "happy", 6)
        await _seed_memory(test_db, str(user.id), "project meeting", "Meeting", ["work"], "focused", 7)

        response = client.post(
            "/api/memories/search/natural",
            params={"query": "coffee with friends", "limit": 10},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["results"][0]["title"] == "Coffee"
