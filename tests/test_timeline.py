"""Tests for the timeline endpoint (Issue 17).

GET /api/timeline supports chronological ordering, date range filtering,
tag/mood filters, and pagination.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone, timedelta

from app.main import app
from app.db import Base, User, Memory, get_db
from app.security import hash_password


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _aware(dt: datetime) -> datetime:
    """Attach UTC tzinfo if naive (SQLite returns naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
    created_at=None,
    tags=None,
    mood="neutral",
):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
        tags=tags if tags is not None else ["test"],
        mood=mood,
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        created_at=created_at or datetime.utcnow(),
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestTimelineChronologicalOrder:
    """Timeline returns memories ordered by event date."""

    @pytest.mark.asyncio
    async def test_timeline_returns_memories_chronologically(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 1, 12, 0, 0)
        await _seed_memory(test_db, str(user1.id), "oldest", "Oldest", created_at=base)
        await _seed_memory(
            test_db, str(user1.id), "newest", "Newest", created_at=base + timedelta(days=5)
        )
        await _seed_memory(
            test_db, str(user1.id), "middle", "Middle", created_at=base + timedelta(days=2)
        )

        response = client.get(
            "/api/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        titles = [item["title"] for item in data]
        assert titles == ["Newest", "Middle", "Oldest"]

    @pytest.mark.asyncio
    async def test_timeline_orders_by_event_date_over_created_at(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        created = datetime(2026, 2, 1, 12, 0, 0)
        # Created first but event is later.
        later_event = await _seed_memory(
            test_db, str(user1.id), "later event", "LaterEvent", created_at=created
        )
        later_event.event_date = created + timedelta(days=10)
        # Created second but event is earlier.
        earlier_event = await _seed_memory(
            test_db, str(user1.id), "earlier event", "EarlierEvent", created_at=created
        )
        earlier_event.event_date = created - timedelta(days=10)
        await test_db.commit()

        response = client.get(
            "/api/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["LaterEvent", "EarlierEvent"]

    @pytest.mark.asyncio
    async def test_timeline_supports_ascending_order(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 1, 12, 0, 0)
        await _seed_memory(test_db, str(user1.id), "a", "A", created_at=base)
        await _seed_memory(
            test_db, str(user1.id), "b", "B", created_at=base + timedelta(days=1)
        )

        response = client.get(
            "/api/timeline?order=asc",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert [item["title"] for item in response.json()] == ["A", "B"]

    @pytest.mark.asyncio
    async def test_timeline_only_returns_current_user_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "alice mem", "AliceMem")
        await _seed_memory(test_db, str(user2.id), "bob mem", "BobMem")

        response = client.get(
            "/api/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "AliceMem"


class TestTimelineFiltering:
    """Timeline supports date range, tag, and mood filters."""

    @pytest.mark.asyncio
    async def test_timeline_filters_by_date_range(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 1, 12, 0, 0)
        await _seed_memory(test_db, str(user1.id), "jan", "Jan", created_at=base)
        await _seed_memory(
            test_db, str(user1.id), "jun", "Jun", created_at=base + timedelta(days=150)
        )
        await _seed_memory(
            test_db, str(user1.id), "dec", "Dec", created_at=base + timedelta(days=330)
        )

        response = client.get(
            "/api/timeline",
            params={
                "start_date": "2026-05-01T00:00:00",
                "end_date": "2026-08-01T00:00:00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["Jun"]

    @pytest.mark.asyncio
    async def test_timeline_filters_by_tag(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "work", "Work", tags=["work"])
        await _seed_memory(test_db, str(user1.id), "travel", "Travel", tags=["travel"])

        response = client.get(
            "/api/timeline?tags=work",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["Work"]

    @pytest.mark.asyncio
    async def test_timeline_filters_by_multiple_tags_is_or(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "work", "Work", tags=["work"])
        await _seed_memory(test_db, str(user1.id), "travel", "Travel", tags=["travel"])
        await _seed_memory(test_db, str(user1.id), "food", "Food", tags=["food"])

        response = client.get(
            "/api/timeline?tags=work&tags=travel",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        titles = sorted(item["title"] for item in response.json())
        assert titles == ["Travel", "Work"]

    @pytest.mark.asyncio
    async def test_timeline_filters_by_mood(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(test_db, str(user1.id), "happy", "Happy", mood="happy")
        await _seed_memory(test_db, str(user1.id), "sad", "Sad", mood="sad")

        response = client.get(
            "/api/timeline?mood=happy",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["Happy"]


class TestTimelinePagination:
    """Timeline supports limit/offset pagination."""

    @pytest.mark.asyncio
    async def test_timeline_pagination(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        base = datetime(2026, 1, 1, 12, 0, 0)
        for i in range(5):
            await _seed_memory(
                test_db,
                str(user1.id),
                f"mem {i}",
                f"M{i}",
                created_at=base + timedelta(days=i),
            )

        response = client.get(
            "/api/timeline?limit=2&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # DESC order: M4, M3, M2, M1, M0 -> offset 1 gives M3, M2
        assert [item["title"] for item in data] == ["M3", "M2"]

    @pytest.mark.asyncio
    async def test_timeline_requires_authentication(self, client):
        response = client.get("/api/timeline")
        assert response.status_code in (401, 403)
