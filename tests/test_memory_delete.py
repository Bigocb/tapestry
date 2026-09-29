"""Tests for memory deletion endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, Memory, Entity, MemoryEntity, get_db
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


async def _seed_memory(session, user_id, raw_input):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": raw_input, "summary": raw_input},
        tags=["test"],
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def _seed_mention(session, user_id, memory_id, value):
    """Attach a person mention to a memory via the entity service."""
    from app.db.entities import apply_mentions

    entities = await apply_mentions(
        session, user_id, memory_id, [("person", value, None)]
    )
    return entities[0]


class TestMemoryDelete:
    """Test DELETE /api/memories/:id endpoint."""

    @pytest.mark.asyncio
    async def test_delete_memory_removes_memory_and_entities(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "memory to delete")
        entity = await _seed_mention(test_db, str(user1.id), str(memory.id), "Sarah")
        await test_db.commit()

        response = client.delete(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 204

        # The memory is gone.
        mem_result = await test_db.execute(select(Memory).where(Memory.id == memory.id))
        assert mem_result.scalar_one_or_none() is None

        # The mention cascaded away...
        mention_result = await test_db.execute(
            select(MemoryEntity).where(MemoryEntity.memory_id == memory.id)
        )
        assert mention_result.scalars().all() == []

        # ...and the entity's cached mention count was corrected to zero
        # rather than left stale at 1.
        await test_db.refresh(entity)
        assert entity.mention_count == 0

    @pytest.mark.asyncio
    async def test_delete_memory_returns_404_for_other_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user2.id), "bob private")

        response = client.delete(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_memory_returns_404_for_missing_memory(
        self, client, setup_users, get_auth_token
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.delete(
            "/api/memories/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
