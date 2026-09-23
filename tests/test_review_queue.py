"""Tests for the review queue and date-driven timeline behaviour.

Covers:
- Memories with a detected date are used on the timeline, undated ones are not.
- Undated memories are flagged needs_review with reason 'missing_date'.
- GET /api/review returns the queue; GET /api/review/count returns a badge count.
- Setting an event date via PATCH clears the review flag and the memory
  becomes visible on the timeline.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

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


async def _seed_memory(session, user_id, raw_input, title, event_date=None, needs_review=False, review_reason=None):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
        tags=[],
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        event_date=event_date,
        needs_review=needs_review,
        review_reason=review_reason,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestTimelineExcludesUndated:
    """Undated memories must not appear on the timeline."""

    @pytest.mark.asyncio
    async def test_timeline_omits_memories_without_event_date(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db,
            str(user1.id),
            "dated memory",
            "Dated",
            event_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
        )
        await _seed_memory(
            test_db,
            str(user1.id),
            "undated memory",
            "Undated",
            event_date=None,
            needs_review=True,
            review_reason="missing_date",
        )

        response = client.get("/api/timeline", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        titles = [item["title"] for item in response.json()]
        assert titles == ["Dated"]


class TestReviewQueue:
    """Review queue endpoints."""

    @pytest.mark.asyncio
    async def test_review_queue_lists_flagged_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db,
            str(user1.id),
            "needs a date",
            "NeedsDate",
            event_date=None,
            needs_review=True,
            review_reason="missing_date",
        )
        await _seed_memory(
            test_db,
            str(user1.id),
            "fine",
            "Fine",
            event_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        response = client.get("/api/review", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "NeedsDate"
        assert data["items"][0]["needs_review"] is True
        assert data["items"][0]["review_reason"] == "missing_date"

    @pytest.mark.asyncio
    async def test_review_queue_scoped_to_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db, str(user2.id), "bob's", "Bob", event_date=None, needs_review=True
        )

        response = client.get("/api/review", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_review_count_endpoint(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        await _seed_memory(
            test_db, str(user1.id), "a", "A", event_date=None, needs_review=True
        )
        await _seed_memory(
            test_db, str(user1.id), "b", "B", event_date=None, needs_review=True
        )

        response = client.get(
            "/api/review/count", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["count"] == 2

    @pytest.mark.asyncio
    async def test_review_queue_requires_authentication(self, client):
        assert client.get("/api/review").status_code in (401, 403)
        assert client.get("/api/review/count").status_code in (401, 403)


class TestSettingDateClearsReview:
    """PATCH with an event_date clears the review flag and surfaces the memory."""

    @pytest.mark.asyncio
    async def test_patch_event_date_clears_review_flag(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db,
            str(user1.id),
            "no date yet",
            "NoDate",
            event_date=None,
            needs_review=True,
            review_reason="missing_date",
        )

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"event_date": "2024-03-15T00:00:00Z"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["needs_review"] is False
        assert data["review_reason"] is None
        assert data["event_date"] is not None

        # Now visible on the timeline.
        timeline = client.get("/api/timeline", headers={"Authorization": f"Bearer {token}"})
        assert [item["title"] for item in timeline.json()] == ["NoDate"]

        # And gone from the review queue.
        queue = client.get("/api/review", headers={"Authorization": f"Bearer {token}"})
        assert queue.json()["total"] == 0


class TestCaptureSetsReviewFlag:
    """Capturing text with no inferable date flags the memory for review."""

    @pytest.mark.asyncio
    async def test_capture_without_date_is_flagged(
        self, client, test_db, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def fake_structure(raw_input: str) -> StructuredMemory:
            return StructuredMemory(
                title="No date memory",
                summary=raw_input,
                entities=[],
                mood=None,
                importance_level=5,
                initial_tags=["test"],
                event_date=None,
            )

        monkeypatch.setattr("app.routes.memories.structure_memory", fake_structure)
        # Prevent the background pipeline from running so we observe capture state.
        monkeypatch.setattr(
            "app.routes.memories._schedule_refinement",
            lambda *a, **k: None,
        )

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Just a passing thought with no particular date."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["needs_review"] is True
        assert data["review_reason"] == "missing_date"

    @pytest.mark.asyncio
    async def test_capture_with_date_is_not_flagged(
        self, client, test_db, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def fake_structure(raw_input: str) -> StructuredMemory:
            return StructuredMemory(
                title="Dated memory",
                summary=raw_input,
                entities=[],
                mood=None,
                importance_level=5,
                initial_tags=["test"],
                event_date=datetime(2020, 6, 1, tzinfo=timezone.utc),
            )

        monkeypatch.setattr("app.routes.memories.structure_memory", fake_structure)
        monkeypatch.setattr(
            "app.routes.memories._schedule_refinement",
            lambda *a, **k: None,
        )

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Back in 2020 we moved to Portland."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["needs_review"] is False
        assert data["review_reason"] is None
