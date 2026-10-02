"""Tests for changing a password while signed in.

Knowing the current password is required, even though a reset link exists. The
reset link is for when the password is forgotten; this is for a session that is
already open, and requiring the current password stops a borrowed session from
locking the owner out.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, User, get_db
from app.security import hash_password


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


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
def setup_user(test_db):
    async def _setup():
        user = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        test_db.add(user)
        await test_db.commit()
        await test_db.refresh(user)
        return user

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


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_the_password_can_be_changed(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")

        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "a-much-longer-secret",
            },
            headers=headers,
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_the_new_password_is_the_one_that_works(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")
        client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "a-much-longer-secret",
            },
            headers=headers,
        )

        old = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "password123"},
        )
        new = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "a-much-longer-secret"},
        )

        assert old.status_code == 401
        assert new.status_code == 200

    @pytest.mark.asyncio
    async def test_the_wrong_current_password_is_refused(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")

        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "not-my-password",
                "new_password": "a-much-longer-secret",
            },
            headers=headers,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_a_refused_change_leaves_the_password_alone(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")
        client.post(
            "/api/auth/change-password",
            json={
                "current_password": "not-my-password",
                "new_password": "a-much-longer-secret",
            },
            headers=headers,
        )

        assert (
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "password123"},
            ).status_code
            == 200
        )

    @pytest.mark.asyncio
    async def test_a_short_new_password_is_refused(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")

        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "password123", "new_password": "short"},
            headers=headers,
        )

        # Pydantic's length rule rejects it before the handler runs.
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_changing_to_the_same_password_is_refused(
        self, client, setup_user, auth
    ):
        await setup_user()
        headers = auth("alice", "password123")

        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "password123",
            },
            headers=headers,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_it_requires_being_signed_in(self, client, setup_user):
        await setup_user()

        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "a-much-longer-secret",
            },
        )

        assert response.status_code in (401, 403)
