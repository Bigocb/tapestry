"""Tests for insights endpoints (Issue 18).

GET /api/insights/stats, /trends, /word-cloud, /achievements.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

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


async def _seed_memory(
    session,
    user_id,
    raw_input,
    title,
    summary=None,
    created_at=None,
    tags=None,
    mood="neutral",
    importance_level=5,
):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": summary or raw_input},
        tags=tags if tags is not None else [],
        mood=mood,
        importance_level=importance_level,
        processing_state="enriched",
        related_memory_ids=[],
        created_at=created_at or datetime.utcnow(),
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def _seed_story(session, user_id, title):
    story = Story(
        user_id=user_id,
        title=title,
        narrative="Once upon a time.",
        memory_ids=[],
        story_type="digest",
    )
    session.add(story)
    await session.commit()
    await session.refresh(story)
    return story


class TestInsightsStats:
    """GET /api/insights/stats."""

    @pytest.mark.asyncio
    async def test_stats_aggregates_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db, str(user1.id), "one", "One", mood="happy", tags=["work"], importance_level=4
        )
        await _seed_memory(
            test_db, str(user1.id), "two", "Two", mood="happy", tags=["work"], importance_level=6
        )
        await _seed_memory(
            test_db, str(user1.id), "three", "Three", mood="sad", tags=["personal"], importance_level=2
        )

        response = client.get(
            "/api/insights/stats",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_memories"] == 3
        assert data["memories_by_mood"]["happy"] == 2
        assert data["memories_by_mood"]["sad"] == 1
        assert data["memories_by_tag"]["work"] == 2
        assert data["memories_by_tag"]["personal"] == 1
        assert data["average_importance"] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_stats_empty_for_new_user(
        self, client, setup_users, get_auth_token
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.get(
            "/api/insights/stats",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_memories"] == 0
        assert data["memories_by_mood"] == {}
        assert data["average_importance"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_scoped_to_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "mine", "Mine")
        await _seed_memory(test_db, str(user2.id), "theirs", "Theirs")

        response = client.get(
            "/api/insights/stats",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["total_memories"] == 1


class TestInsightsTrends:
    """GET /api/insights/trends."""

    @pytest.mark.asyncio
    async def test_trends_counts_memories_per_week(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 5, 12, 0, 0)  # Monday
        await _seed_memory(test_db, str(user1.id), "a", "A", created_at=base)
        await _seed_memory(
            test_db, str(user1.id), "b", "B", created_at=base + timedelta(days=1)
        )
        await _seed_memory(
            test_db, str(user1.id), "c", "C", created_at=base + timedelta(days=8)
        )

        response = client.get(
            "/api/insights/trends",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        totals = [point["value"] for point in data["memories_per_week"]]
        assert sum(totals) == 3

    @pytest.mark.asyncio
    async def test_trends_includes_mood_trend(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 5, 12, 0, 0)
        await _seed_memory(test_db, str(user1.id), "a", "A", mood="happy", created_at=base)
        await _seed_memory(test_db, str(user1.id), "b", "B", mood="sad", created_at=base)

        response = client.get(
            "/api/insights/trends",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert len(response.json()["mood_trend"]) >= 1


class TestInsightsWordCloud:
    """GET /api/insights/word-cloud."""

    @pytest.mark.asyncio
    async def test_word_cloud_frequencies(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db,
            str(user1.id),
            "hiking trip",
            "Mountain hiking",
            summary="Went hiking in the mountains with friends",
        )
        await _seed_memory(
            test_db,
            str(user1.id),
            "another hike",
            "Hiking again",
            summary="More hiking adventures",
        )

        response = client.get(
            "/api/insights/word-cloud",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        words = {item["word"]: item["frequency"] for item in data}
        assert words.get("hiking", 0) >= 2

    @pytest.mark.asyncio
    async def test_word_cloud_excludes_stopwords(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db,
            str(user1.id),
            "the and with",
            "The and with",
            summary="the and with the and with",
        )

        response = client.get(
            "/api/insights/word-cloud",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        words = {item["word"] for item in response.json()}
        assert "the" not in words
        assert "and" not in words


class TestInsightsAchievements:
    """GET /api/insights/achievements."""

    @pytest.mark.asyncio
    async def test_achievements_first_memory_earned(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "first", "First")

        response = client.get(
            "/api/insights/achievements",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        by_id = {item["id"]: item for item in data}
        assert by_id["first_memory"]["earned"] is True
        assert by_id["ten_memories"]["earned"] is False
        assert 0.0 <= by_id["ten_memories"]["progress"] < 1.0

    @pytest.mark.asyncio
    async def test_achievements_first_story(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_story(test_db, str(user1.id), "My Story")

        response = client.get(
            "/api/insights/achievements",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        by_id = {item["id"]: item for item in response.json()}
        assert by_id["first_story"]["earned"] is True


class TestInsightsAuth:
    """Insights endpoints require authentication."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/api/insights/stats",
            "/api/insights/trends",
            "/api/insights/word-cloud",
            "/api/insights/achievements",
        ],
    )
    async def test_insights_requires_authentication(self, client, path):
        response = client.get(path)
        assert response.status_code in (401, 403)
