"""Tests for memory update endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, Memory, get_db
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


async def _seed_memory(session, user_id, raw_input, title):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
        tags=["initial"],
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestMemoryUpdate:
    """Test PATCH /api/memories/:id endpoint."""

    @pytest.mark.asyncio
    async def test_update_memory_partial_fields(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "original text", "Original")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={
                "tags": ["work", "career"],
                "mood": "excited",
                "importance_level": 8,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tags"] == ["work", "career"]
        assert data["mood"] == "excited"
        assert data["importance_level"] == 8
        assert data["raw_input"] == "original text"  # unchanged

    @pytest.mark.asyncio
    async def test_update_memory_structured_content(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "original text", "Original")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={
                "structured_content": {
                    "title": "Updated Title",
                    "summary": "Updated summary text.",
                    "entities": [{"type": "person", "value": "Sarah"}],
                    "mood": "happy",
                    "importance_level": 7,
                    "initial_tags": ["work", "friends"],
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["structured_content"]["title"] == "Updated Title"
        assert data["mood"] == "happy"
        assert data["importance_level"] == 7
        assert data["tags"] == ["work", "friends"]

    @pytest.mark.asyncio
    async def test_update_memory_with_event_date_in_structured_content(
        self, client, test_db, setup_users, get_auth_token
    ):
        """Editing a pipeline-processed memory must not crash.

        The agents store structured_content with event_date as an ISO string.
        PATCH parses that value back into a datetime; a missing import used to
        raise NameError and return 500 for every such memory.
        """
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        memory = Memory(
            raw_input="Born in Conway",
            input_type="text",
            user_id=str(user1.id),
            structured_content={
                "title": "Birth",
                "summary": "Born in Conway",
                "entities": [],
                "event_date": "1976-07-29T00:00:00Z",
            },
            tags=["birth"],
            mood="neutral",
            importance_level=8,
            processing_state="enriched",
            related_memory_ids=[],
        )
        test_db.add(memory)
        await test_db.commit()
        await test_db.refresh(memory)

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"mood": "happy"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mood"] == "happy"
        # The stored ISO event_date must survive the round trip.
        assert data["event_date"] is not None

    @pytest.mark.asyncio
    async def test_update_persists_title_and_summary(
        self, client, test_db, setup_users, get_auth_token
    ):
        """The editor's payload (title + body) must actually persist.

        MemoryUpdate previously had no `title`/`summary` field and Pydantic
        silently ignored unknown keys, so saving returned 200 while discarding
        the user's edits.
        """
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "original body", "Original")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"title": "New Title", "summary": "New body text."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Title"
        assert data["summary"] == "New body text."

        # And it must be read back on a fresh request.
        follow_up = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert follow_up.json()["title"] == "New Title"
        assert follow_up.json()["summary"] == "New body text."

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_fields(
        self, client, test_db, setup_users, get_auth_token
    ):
        """Unknown fields must fail loudly instead of being silently dropped.

        This is the guard that stops frontend/backend field drift from turning
        into silent data loss.
        """
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "text", "Title")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"not_a_real_field": "value"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_user_edit_wins_over_stored_structured_content(
        self, client, test_db, setup_users, get_auth_token
    ):
        """An explicit edit must not be clobbered by stale agent-derived values.

        The enrichment agent writes importance_level/mood into
        structured_content. Re-reading those after applying the user's update
        used to overwrite the user's value.
        """
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        memory = Memory(
            raw_input="text",
            input_type="text",
            user_id=str(user1.id),
            structured_content={
                "title": "T",
                "summary": "S",
                "entities": [],
                "mood": "neutral",
                "importance_level": 8,
                "initial_tags": ["old"],
            },
            tags=["old"],
            mood="neutral",
            importance_level=8,
            processing_state="enriched",
            related_memory_ids=[],
        )
        test_db.add(memory)
        await test_db.commit()
        await test_db.refresh(memory)

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"importance_level": 2, "mood": "excited", "tags": ["brand-new"]},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["importance_level"] == 2
        assert data["mood"] == "excited"
        assert data["tags"] == ["brand-new"]

    @pytest.mark.asyncio
    async def test_update_memory_returns_404_for_other_user(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user2.id), "bob private", "Bob")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"mood": "happy"},
            headers={"Authorization": f"Bearer {token1}"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_memory_returns_422_for_invalid_importance(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "text", "Title")

        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"importance_level": 99},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_memory_related_ids(
        self, client, test_db, setup_users, get_auth_token
    ):
        import uuid

        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "text", "Title")

        related_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/memories/{memory.id}",
            json={"related_memory_ids": [related_id]},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["related_memory_ids"] == [related_id]
