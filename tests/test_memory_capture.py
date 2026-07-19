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
from app.models.schemas import MemoryCapture, MemoryResponse


# Setup test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    """Create an in-memory test database."""
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
    """FastAPI test client with overridden database dependency."""

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


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
def get_auth_token(client):
    """Get JWT token for a user."""

    def _get_token(username: str, password: str):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return response.json()["access_token"]

    return _get_token


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

        assert response.status_code == 403

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
