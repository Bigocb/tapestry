"""Tests for per-user LLM provider settings.

Provider settings are per user: one person can point capture at a local model
while another uses a hosted one, each with their own key. Keys are stored
encrypted and are never returned — the API says only whether one is set.

Embeddings are the exception. The stored vectors were made by one model, and a
different one produces vectors of a different shape that compare meaninglessly,
so the embedding model is locked until re-embedding exists.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, User, get_db
from app.db.models import LLMSetting
from app.security import hash_password


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    # A fixed key so an encrypted value is stable within a test run.
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", "test-encryption-key")


@pytest.fixture
async def test_db():
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
def auth(client):
    def _auth(username: str, password: str) -> dict:
        token = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        ).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _auth


def _by_role(entries: list[dict], role: str) -> dict:
    return next(entry for entry in entries if entry["role"] == role)


class TestSettingAModel:
    @pytest.mark.asyncio
    async def test_a_role_can_be_pointed_at_a_model(
        self, client, setup_users, auth
    ):
        await setup_users()
        headers = auth("alice", "password123")

        response = client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_the_setting_is_read_back(self, client, setup_users, auth):
        await setup_users()
        headers = auth("alice", "password123")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers=headers,
        )

        entries = client.get("/api/settings/llm", headers=headers).json()

        assert _by_role(entries, "capture")["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_every_role_is_listed(self, client, setup_users, auth):
        await setup_users()
        headers = auth("alice", "password123")

        entries = client.get("/api/settings/llm", headers=headers).json()

        roles = {entry["role"] for entry in entries}
        assert {"capture", "refinement", "search", "story", "embedding"} <= roles

    @pytest.mark.asyncio
    async def test_an_unknown_role_is_refused(self, client, setup_users, auth):
        await setup_users()
        headers = auth("alice", "password123")

        response = client.put(
            "/api/settings/llm/teleportation",
            json={"model": "whatever"},
            headers=headers,
        )

        assert response.status_code in (400, 404)


class TestKeysAreSecret:
    @pytest.mark.asyncio
    async def test_a_key_is_never_returned(self, client, setup_users, auth):
        await setup_users()
        headers = auth("alice", "password123")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-secret"},
            headers=headers,
        )

        entries = client.get("/api/settings/llm", headers=headers).json()
        capture = _by_role(entries, "capture")

        assert capture["has_api_key"] is True
        assert "sk-secret" not in str(entries)

    @pytest.mark.asyncio
    async def test_the_key_is_stored_encrypted(
        self, client, setup_users, auth, test_db
    ):
        await setup_users()
        headers = auth("alice", "password123")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-secret"},
            headers=headers,
        )

        row = (
            await test_db.execute(select(LLMSetting))
        ).scalars().first()
        assert row.api_key_encrypted
        assert "sk-secret" not in row.api_key_encrypted

    @pytest.mark.asyncio
    async def test_omitting_the_key_keeps_the_stored_one(
        self, client, setup_users, auth
    ):
        await setup_users()
        headers = auth("alice", "password123")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-secret"},
            headers=headers,
        )

        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers=headers,
        )

        entries = client.get("/api/settings/llm", headers=headers).json()
        assert _by_role(entries, "capture")["has_api_key"] is True

    @pytest.mark.asyncio
    async def test_an_empty_key_clears_it(self, client, setup_users, auth):
        await setup_users()
        headers = auth("alice", "password123")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o", "api_key": "sk-secret"},
            headers=headers,
        )

        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o", "api_key": ""},
            headers=headers,
        )

        entries = client.get("/api/settings/llm", headers=headers).json()
        assert _by_role(entries, "capture")["has_api_key"] is False


class TestPerUser:
    @pytest.mark.asyncio
    async def test_one_users_setting_is_not_anothers(
        self, client, setup_users, auth
    ):
        await setup_users()
        alice = auth("alice", "password123")
        bob = auth("bob", "password456")
        client.put(
            "/api/settings/llm/capture",
            json={"provider": "openai", "model": "gpt-4o"},
            headers=alice,
        )

        bob_entries = client.get("/api/settings/llm", headers=bob).json()

        assert _by_role(bob_entries, "capture")["model"] != "gpt-4o"

    @pytest.mark.asyncio
    async def test_it_requires_being_signed_in(self, client, setup_users):
        await setup_users()

        response = client.get("/api/settings/llm")

        assert response.status_code in (401, 403)


class TestEmbeddingsAreLocked:
    @pytest.mark.asyncio
    async def test_the_embedding_model_cannot_be_changed(
        self, client, setup_users, auth
    ):
        await setup_users()
        headers = auth("alice", "password123")

        response = client.put(
            "/api/settings/llm/embedding",
            json={"provider": "openai", "model": "text-embedding-3-small"},
            headers=headers,
        )

        # Stored vectors were made by one model; a different one produces
        # vectors that compare meaninglessly.
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_the_embedding_key_can_still_be_set(
        self, client, setup_users, auth
    ):
        await setup_users()
        headers = auth("alice", "password123")

        response = client.put(
            "/api/settings/llm/embedding",
            json={"api_key": "sk-embed"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["has_api_key"] is True
