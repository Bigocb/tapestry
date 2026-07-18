"""Tests for JWT authentication and user management.

RED: Test-driven development for auth flows:
- User registration (create account)
- User login (get JWT token)
- Token validation
- Protected route access
- User isolation
- Error cases
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import json

from app.main import app
from app.db import Base, User, get_db
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
)


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


class TestSecurityUtilities:
    """Test password hashing and JWT utilities."""

    def test_hash_password(self):
        """Password hashing works."""
        password = "mysecurepassword123"
        hashed = hash_password(password)
        assert hashed != password
        assert len(hashed) > 20

    def test_verify_password_correct(self):
        """Verify correct password."""
        password = "mysecurepassword123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Reject incorrect password."""
        password = "mysecurepassword123"
        hashed = hash_password(password)
        assert verify_password("wrongpassword", hashed) is False

    def test_create_access_token(self):
        """Create JWT access token."""
        token = create_access_token(user_id="test-user-id", username="testuser")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_access_token_valid(self):
        """Decode valid JWT token."""
        token = create_access_token(user_id="test-user-id", username="testuser")
        token_data = decode_access_token(token)
        assert token_data is not None
        assert token_data.user_id == "test-user-id"
        assert token_data.username == "testuser"

    def test_decode_access_token_invalid(self):
        """Reject invalid JWT token."""
        token_data = decode_access_token("invalid.token.here")
        assert token_data is None

    def test_decode_access_token_empty(self):
        """Reject empty token."""
        token_data = decode_access_token("")
        assert token_data is None


class TestUserRegistration:
    """Test user registration endpoint."""

    def test_register_valid(self, client):
        """Register a valid new user."""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@example.com"
        assert "id" in data
        assert "created_at" in data

    def test_register_duplicate_username(self, client):
        """Cannot register duplicate username."""
        # First registration
        client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "first@example.com",
                "password": "securepassword123",
            },
        )

        # Try to register same username
        response = client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "second@example.com",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_register_duplicate_email(self, client):
        """Cannot register duplicate email."""
        # First registration
        client.post(
            "/api/auth/register",
            json={
                "username": "user1",
                "email": "same@example.com",
                "password": "securepassword123",
            },
        )

        # Try to register same email
        response = client.post(
            "/api/auth/register",
            json={
                "username": "user2",
                "email": "same@example.com",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    def test_register_invalid_email(self, client):
        """Reject invalid email."""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "not-an-email",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 422  # Validation error

    def test_register_password_too_short(self, client):
        """Reject password that's too short."""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 422

    def test_register_username_too_short(self, client):
        """Reject username that's too short."""
        response = client.post(
            "/api/auth/register",
            json={
                "username": "ab",
                "email": "test@example.com",
                "password": "securepassword123",
            },
        )
        assert response.status_code == 422


class TestUserLogin:
    """Test user login endpoint."""

    def test_login_valid(self, client):
        """Login with valid credentials."""
        # Register first
        client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepassword123",
            },
        )

        # Login
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "securepassword123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_username(self, client):
        """Login with non-existent username."""
        response = client.post(
            "/api/auth/login",
            json={"username": "nonexistent", "password": "password123"},
        )
        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]

    def test_login_invalid_password(self, client):
        """Login with wrong password."""
        # Register first
        client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepassword123",
            },
        )

        # Try login with wrong password
        response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]


class TestTokenRefresh:
    """Test token refresh endpoint."""

    def test_refresh_valid_token(self, client):
        """Refresh a valid token."""
        # Register and login
        client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "securepassword123",
            },
        )

        login_response = client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "securepassword123"},
        )
        token = login_response.json()["access_token"]

        # Refresh token
        response = client.post("/api/auth/refresh", json={"token": token})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_refresh_invalid_token(self, client):
        """Refresh with invalid token."""
        response = client.post(
            "/api/auth/refresh", json={"token": "invalid.token.here"}
        )
        assert response.status_code == 401

    def test_refresh_nonexistent_user(self, client):
        """Refresh token for deleted user."""
        # Create token with fake user ID
        token = create_access_token(
            user_id="00000000-0000-0000-0000-000000000000", username="fakeusernamexyz"
        )

        response = client.post("/api/auth/refresh", json={"token": token})
        assert response.status_code == 401
        assert "User not found" in response.json()["detail"]


class TestUserIsolation:
    """Test that users are properly isolated."""

    def test_different_users_different_tokens(self, client):
        """Different users get different tokens."""
        # Register user 1
        client.post(
            "/api/auth/register",
            json={
                "username": "user1",
                "email": "user1@example.com",
                "password": "password123",
            },
        )

        # Register user 2
        client.post(
            "/api/auth/register",
            json={
                "username": "user2",
                "email": "user2@example.com",
                "password": "password123",
            },
        )

        # Login user 1
        response1 = client.post(
            "/api/auth/login", json={"username": "user1", "password": "password123"}
        )
        token1 = response1.json()["access_token"]

        # Login user 2
        response2 = client.post(
            "/api/auth/login", json={"username": "user2", "password": "password123"}
        )
        token2 = response2.json()["access_token"]

        # Tokens are different
        assert token1 != token2

        # Tokens contain different user IDs
        data1 = decode_access_token(token1)
        data2 = decode_access_token(token2)
        assert data1.user_id != data2.user_id
