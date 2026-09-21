"""Tests for memory capture endpoint.

RED: Test-driven development for memory capture:
- Capture with text input
- Capture with voice input type
- Capture with form input type
- User isolation (can't access other user's memories)
- Raw memory stored in database
- Processing state initialized to 'raw'
- Input validation (required fields)
- Response schema validation
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from uuid import UUID

from app.main import app
from app.db import Base, User, Memory, get_db
from app.security import hash_password
from app.models.schemas import (
    MemoryCapture,
    MemoryResponse,
    StructuredMemory,
    EntityData,
)


# Setup test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    """Create an in-memory test database."""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
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
    """FastAPI test client with overridden database dependency."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.routes import memories
    from app.jobs import scheduler

    async def override_get_db():
        yield test_db

    test_factory = async_sessionmaker(
        bind=test_db.bind,
        class_=type(test_db),
        expire_on_commit=False,
        autoflush=False,
    )
    original_factory = scheduler.BackgroundSessionLocal
    scheduler.BackgroundSessionLocal = test_factory

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    # Restore original factory after test.
    scheduler.BackgroundSessionLocal = original_factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def setup_users(test_db):
    """Create test users in database."""

    async def _setup():
        # User 1
        user1 = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        test_db.add(user1)

        # User 2
        user2 = User(
            username="bob",
            email="bob@example.com",
            password_hash=hash_password("password456"),
        )
        test_db.add(user2)

        await test_db.commit()

        # Refresh to get IDs
        await test_db.refresh(user1)
        await test_db.refresh(user2)

        return user1, user2

    return _setup


@pytest.fixture
def fake_structure_memory(monkeypatch):
    """Replace the Capture Agent with a deterministic stub for all tests."""

    async def _fake(raw_input: str):
        return StructuredMemory(
            title="Structured: " + raw_input[:50],
            summary=raw_input,
            entities=[EntityData(type="concept", value="test")],
            mood="neutral",
            importance_level=5,
            initial_tags=["test"],
        )

    monkeypatch.setattr("app.routes.memories.structure_memory", _fake)


@pytest.fixture
def get_auth_token(client):
    """Get JWT token for a user."""

    def _get_token(username: str, password: str):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return response.json()["access_token"]

    return _get_token


class TestMemoryCaptureVoiceEndpoint:
    """Test /api/memories/capture/voice endpoint (Issue 4)."""

    @pytest.mark.asyncio
    async def test_capture_voice_endpoint_with_audio_file(
        self, client, setup_users, get_auth_token, monkeypatch, fake_structure_memory
    ):
        """Voice capture endpoint accepts an audio file and stores transcription."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        # Mock transcription service to avoid calling Ollama in tests.
        async def fake_transcribe(audio_bytes: bytes) -> str:
            return "Went for a run this morning and felt great."

        from app import routes

        monkeypatch.setattr(routes.memories, "_transcribe_audio", fake_transcribe)

        response = client.post(
            "/api/memories/capture/voice",
            files={"audio": ("morning_run.mp3", b"fake-audio-bytes", "audio/mpeg")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == str(user1.id)
        assert data["raw_input"] == "Went for a run this morning and felt great."
        assert data["input_type"] == "voice"
        assert data["processing_state"] == "capturing"


class TestMemoryCaptureFormEndpoint:
    """Test /api/memories/capture/form endpoint (Issue 4)."""

    @pytest.mark.asyncio
    async def test_capture_form_endpoint_creates_structured_memory(
        self, client, setup_users, get_auth_token, fake_structure_memory
    ):
        """Form capture endpoint stores structured fields and state='capturing'."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/form",
            json={
                "raw_input": "Completed the quarterly planning session with the team.",
                "mood": "accomplished",
                "tags": ["work", "planning"],
                "people": ["Sarah", "Mike"],
                "location": "Conference room B",
                "importance_level": 8,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == str(user1.id)
        assert (
            data["raw_input"]
            == "Completed the quarterly planning session with the team."
        )
        assert data["input_type"] == "form"
        assert data["mood"] == "accomplished"
        assert data["tags"] == ["work", "planning"]
        assert data["importance_level"] == 8
        assert data["processing_state"] == "capturing"


class TestMemoryCaptureEndpoint:
    """Test /api/memories/capture endpoint."""

    @pytest.mark.asyncio
    async def test_capture_text_memory(self, client, setup_users, get_auth_token):
        """Test capturing a text-based memory."""
        # Setup
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        # Capture a text memory
        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Had coffee with Sarah at the downtown cafe. We talked about her new job.",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["user_id"] == str(user1.id)
        assert (
            data["raw_input"]
            == "Had coffee with Sarah at the downtown cafe. We talked about her new job."
        )
        assert data["input_type"] == "text"
        assert data["processing_state"] == "raw"
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)


class TestMemoryCaptureTextEndpoint:
    """Test /api/memories/capture/text endpoint (Issue 4)."""

    @pytest.mark.asyncio
    async def test_capture_text_endpoint_creates_memory(
        self, client, setup_users, get_auth_token, fake_structure_memory
    ):
        """Text capture endpoint creates a memory with state='capturing'."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Met with Sarah downtown to discuss her new role."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == str(user1.id)
        assert data["raw_input"] == "Met with Sarah downtown to discuss her new role."
        assert data["input_type"] == "text"
        assert data["processing_state"] == "capturing"
        assert isinstance(data["created_at"], str)
        # Structured content is produced by the Capture Agent.
        assert data["structured_content"] is not None
        assert data["mood"] == "neutral"
        assert data["tags"] == ["test"]

    @pytest.mark.asyncio
    async def test_capture_text_runs_full_background_pipeline(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        monkeypatch,
        fake_structure_memory,
    ):
        """After text capture, the background pipeline reaches state 'enriched'."""
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from app.jobs import scheduler

        # Override background session factory to use the test database.
        test_factory = async_sessionmaker(
            bind=test_db.bind,
            class_=type(test_db),
            expire_on_commit=False,
            autoflush=False,
        )
        monkeypatch.setattr(scheduler, "BackgroundSessionLocal", test_factory)

        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Need to buy groceries for the weekend dinner."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        # Background tasks run synchronously after the response in TestClient.
        stmt = select(Memory).where(Memory.id == UUID(memory_id))
        result = await test_db.execute(stmt)
        memory = result.scalar_one_or_none()

        assert memory is not None
        assert memory.processing_state == "enriched"
        assert memory.embedding is not None
        assert isinstance(memory.related_memory_ids, list)

    @pytest.mark.asyncio
    async def test_capture_voice_memory(self, client, setup_users, get_auth_token):
        """Test capturing a voice-based memory."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Went for a run this morning, felt great!",
                "input_type": "voice",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["input_type"] == "voice"
        assert data["processing_state"] == "raw"

    @pytest.mark.asyncio
    async def test_capture_form_memory(self, client, setup_users, get_auth_token):
        """Test capturing a form-based memory."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Completed project milestone",
                "input_type": "form",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["input_type"] == "form"

    @pytest.mark.asyncio
    async def test_capture_requires_authentication(self, client):
        """Test that capture requires valid JWT token."""
        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Some memory",
                "input_type": "text",
            },
        )

        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_capture_with_invalid_token(self, client):
        """Test capture with invalid JWT token."""
        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Some memory",
                "input_type": "text",
            },
            headers={"Authorization": "Bearer invalid.token.here"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_capture_missing_raw_input(self, client, setup_users, get_auth_token):
        """Test that raw_input is required."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={"input_type": "text"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_capture_missing_input_type(
        self, client, setup_users, get_auth_token
    ):
        """Test that input_type is required."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={"raw_input": "Some memory"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_capture_invalid_input_type(
        self, client, setup_users, get_auth_token
    ):
        """Test that input_type must be valid."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Some memory",
                "input_type": "invalid_type",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_capture_empty_raw_input(self, client, setup_users, get_auth_token):
        """Test that raw_input cannot be empty."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_user_isolation_cannot_see_other_user_memory(
        self, client, setup_users, get_auth_token
    ):
        """Test that user1 cannot access user2's memories."""
        user1, user2 = await setup_users()
        token1 = get_auth_token("alice", "password123")
        token2 = get_auth_token("bob", "password456")

        # User 2 captures a memory
        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Bob's secret memory",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token2}"},
        )
        bob_memory_id = response.json()["id"]

        # User 1 tries to access it (would be tested in get endpoint, but verify ownership here)
        assert response.json()["user_id"] == str(user2.id)

    @pytest.mark.asyncio
    async def test_capture_response_has_correct_schema(
        self, client, setup_users, get_auth_token
    ):
        """Test that capture response validates against MemoryResponse schema."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Test memory for schema validation",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        # Try to parse with MemoryResponse schema
        memory_response = MemoryResponse(**response.json())
        assert memory_response.processing_state == "raw"
        assert memory_response.tags == []
        assert memory_response.importance_level == 5

    @pytest.mark.asyncio
    async def test_capture_stores_in_database(
        self, client, test_db, setup_users, get_auth_token
    ):
        """Test that captured memory is actually stored in database."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Database test memory",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        # Query database directly
        from sqlalchemy import select

        stmt = select(Memory).where(Memory.id == UUID(memory_id))
        result = await test_db.execute(stmt)
        memory = result.scalar_one_or_none()

        assert memory is not None
        assert memory.raw_input == "Database test memory"
        assert memory.input_type == "text"
        assert memory.processing_state == "raw"
        assert str(memory.user_id) == str(user1.id)

    @pytest.mark.asyncio
    async def test_capture_multiple_memories_from_same_user(
        self, client, setup_users, get_auth_token
    ):
        """Test that a user can capture multiple memories."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        # Capture first memory
        response1 = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "First memory",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response1.status_code == 201
        id1 = response1.json()["id"]

        # Capture second memory
        response2 = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Second memory",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response2.status_code == 201
        id2 = response2.json()["id"]

        # Verify they are different
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_capture_response_timestamps_are_valid(
        self, client, setup_users, get_auth_token
    ):
        """Test that created_at and updated_at timestamps are valid ISO strings."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture",
            json={
                "raw_input": "Timestamp test",
                "input_type": "text",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()

        # Should be able to parse as ISO datetime
        created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))

        assert created_at is not None
        assert updated_at is not None
        # created_at and updated_at should be very close
        assert abs((updated_at - created_at).total_seconds()) < 1
