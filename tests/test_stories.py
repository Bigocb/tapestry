"""Tests for story generation, retrieval, and export endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, Memory, Story, get_db
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


@pytest.fixture
def fake_generate_story(monkeypatch):
    async def _fake(story_type, memories, custom_prompt=None):
        titles = ", ".join(m.get("title", "Memory") for m in memories)
        return f"# {story_type.title()} Story\n\nThis story covers: {titles}."

    monkeypatch.setattr("app.routes.stories.generate_story", _fake)


async def _seed_memory(session, user_id, raw_input, title):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
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


class TestStoryGeneration:
    """Test POST /api/stories/generate."""

    @pytest.mark.asyncio
    async def test_generate_story_stores_and_returns_story(
        self, client, test_db, setup_users, get_auth_token, fake_generate_story
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        mem1 = await _seed_memory(test_db, str(user1.id), "first event", "First")
        mem2 = await _seed_memory(test_db, str(user1.id), "second event", "Second")

        response = client.post(
            "/api/stories/generate",
            json={
                "memory_ids": [str(mem1.id), str(mem2.id)],
                "story_type": "chronological",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["story_type"] == "chronological"
        assert "First" in data["narrative"]
        assert "Second" in data["narrative"]
        assert data["memory_ids"] == [str(mem1.id), str(mem2.id)]

    @pytest.mark.asyncio
    async def test_generate_story_rejects_other_user_memories(
        self, client, test_db, setup_users, get_auth_token, fake_generate_story
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        mem = await _seed_memory(test_db, str(user2.id), "bob private", "Bob")

        response = client.post(
            "/api/stories/generate",
            json={
                "memory_ids": [str(mem.id)],
                "story_type": "curated",
            },
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_generate_story_accepts_custom_prompt(
        self, client, test_db, setup_users, get_auth_token, monkeypatch
    ):
        async def _fake(story_type, memories, custom_prompt=None):
            return f"# Custom Story\n\nPrompt: {custom_prompt}"

        monkeypatch.setattr("app.routes.stories.generate_story", _fake)

        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        mem = await _seed_memory(test_db, str(user1.id), "event", "Event")

        response = client.post(
            "/api/stories/generate",
            json={
                "memory_ids": [str(mem.id)],
                "story_type": "thematic",
                "custom_prompt": "Make it funny",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "Make it funny" in data["narrative"]


class TestStoryRetrieval:
    """Test GET /api/stories/:id and GET /api/stories."""

    @pytest.mark.asyncio
    async def test_get_story_by_id_returns_story(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        story = Story(
            user_id=user1.id,
            title="My Story",
            narrative="# My Story\n\nA narrative.",
            memory_ids=[],
            story_type="digest",
        )
        test_db.add(story)
        await test_db.commit()
        await test_db.refresh(story)

        response = client.get(
            f"/api/stories/{story.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "My Story"
        assert data["narrative"] == "# My Story\n\nA narrative."

    @pytest.mark.asyncio
    async def test_get_story_by_id_returns_404_for_other_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        story = Story(
            user_id=user2.id,
            title="Bob Story",
            narrative="# Bob Story",
            memory_ids=[],
            story_type="digest",
        )
        test_db.add(story)
        await test_db.commit()
        await test_db.refresh(story)

        response = client.get(
            f"/api/stories/{story.id}",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_stories_returns_user_stories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        s1 = Story(
            user_id=user1.id,
            title="Alice Story 1",
            narrative="# Story 1",
            memory_ids=[],
            story_type="curated",
        )
        s2 = Story(
            user_id=user2.id,
            title="Bob Story",
            narrative="# Bob",
            memory_ids=[],
            story_type="curated",
        )
        test_db.add(s1)
        test_db.add(s2)
        await test_db.commit()
        await test_db.refresh(s1)
        await test_db.refresh(s2)

        response = client.get(
            "/api/stories",
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Alice Story 1"


class TestStoryExport:
    """Test POST /api/stories/:id/export."""

    @pytest.mark.asyncio
    async def test_export_story_to_markdown(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        story = Story(
            user_id=user1.id,
            title="Export Story",
            narrative="# Export Story\n\nText.",
            memory_ids=[],
            story_type="digest",
        )
        test_db.add(story)
        await test_db.commit()
        await test_db.refresh(story)

        response = client.post(
            f"/api/stories/{story.id}/export",
            json={"format": "markdown"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "markdown"
        assert "# Export Story" in data["content"]

    @pytest.mark.asyncio
    async def test_export_story_to_json(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        story = Story(
            user_id=user1.id,
            title="JSON Story",
            narrative="# JSON Story",
            memory_ids=[],
            story_type="digest",
        )
        test_db.add(story)
        await test_db.commit()
        await test_db.refresh(story)

        response = client.post(
            f"/api/stories/{story.id}/export",
            json={"format": "json"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"
        assert data["content"]["title"] == "JSON Story"
