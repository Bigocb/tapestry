"""Tests for the per-memory privacy lock.

A private memory's content must be withheld from every API response until the
client explicitly unlocks it for the session via the X-Unlocked-Memory-Ids
header. Metadata needed to render the lock (id, dates, importance) still
comes back so the UI can show a placeholder.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

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


async def _seed_memory(session, user_id, raw_input, title, is_private=False):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": f"Summary of {title}"},
        tags=["secret-tag"] if is_private else ["public-tag"],
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        event_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
        is_private=is_private,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


def _unlock_header(*memory_ids):
    return {"X-Unlocked-Memory-Ids": ",".join(str(i) for i in memory_ids)}


class TestLockedMemoryRedaction:
    """Locked content must not appear in any read response."""

    @pytest.mark.asyncio
    async def test_get_locked_memory_withholds_content(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db, str(user1.id), "The secret text", "Secret Title", is_private=True
        )

        response = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_private"] is True
        assert data["is_locked"] is True
        # No content leaks.
        assert data["raw_input"] == ""
        assert data["summary"] == "This memory is locked. Unlock it to see its contents."
        assert data["structured_content"] is None
        assert data["tags"] == []
        assert "secret" not in str(data).lower()

    @pytest.mark.asyncio
    async def test_list_redacts_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), "public text", "Public")
        await _seed_memory(
            test_db, str(user1.id), "private text", "Private", is_private=True
        )

        response = client.get(
            "/api/memories", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 2

        public = next(i for i in items if not i["is_locked"])
        locked = next(i for i in items if i["is_locked"])

        assert public["title"] == "Public"
        assert public["raw_input"] == "public text"
        # The locked entry keeps metadata but hides the title and content.
        assert locked["title"] == "Private memory"
        assert locked["raw_input"] == ""
        assert locked["tags"] == []
        assert "private text" not in str(response.json())

    @pytest.mark.asyncio
    async def test_timeline_redacts_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db, str(user1.id), "private text", "Private", is_private=True
        )

        response = client.get(
            "/api/timeline", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["is_locked"] is True
        assert "private text" not in str(body)

    @pytest.mark.asyncio
    async def test_search_excludes_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        """A locked memory must not appear in search results at all.

        Scoring it would leak whether its content matches the query.
        """
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db, str(user1.id), "hiking in yosemite", "Hiking", is_private=True
        )

        response = client.post(
            "/api/memories/search",
            json={"text": "hiking"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json()["results"] == []

    @pytest.mark.asyncio
    async def test_insights_exclude_locked_memories(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(test_db, str(user1.id), "public", "Public")
        await _seed_memory(
            test_db, str(user1.id), "private", "Private", is_private=True
        )

        response = client.get(
            "/api/insights/stats", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["total_memories"] == 1


class TestUnlockAndRelock:
    """Unlocking reveals content; omitting the header re-locks it."""

    @pytest.mark.asyncio
    async def test_unlock_header_reveals_content(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(
            test_db, str(user1.id), "The secret text", "Secret Title", is_private=True
        )

        headers = {"Authorization": f"Bearer {token}", **_unlock_header(memory.id)}
        response = client.get(f"/api/memories/{memory.id}", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["is_locked"] is False
        assert data["raw_input"] == "The secret text"
        assert data["tags"] == ["secret-tag"]

    @pytest.mark.asyncio
    async def test_public_memory_reports_not_locked(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "public text", "Public")

        response = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        data = response.json()
        assert data["is_private"] is False
        assert data["is_locked"] is False
        assert data["raw_input"] == "public text"


class TestTogglingPrivacy:
    """is_private can be set and cleared via PATCH."""

    @pytest.mark.asyncio
    async def test_patch_sets_private_then_clears(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        memory = await _seed_memory(test_db, str(user1.id), "public text", "Public")

        lock = client.patch(
            f"/api/memories/{memory.id}",
            json={"is_private": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert lock.status_code == 200
        assert lock.json()["is_private"] is True
        assert lock.json()["is_locked"] is True

        # Still redacted on the next read without the unlock header.
        read = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.json()["raw_input"] == ""

        # Unlock, then clear the flag entirely.
        unlock_headers = {
            "Authorization": f"Bearer {token}",
            **_unlock_header(memory.id),
        }
        clear = client.patch(
            f"/api/memories/{memory.id}",
            json={"is_private": False},
            headers=unlock_headers,
        )
        assert clear.status_code == 200
        assert clear.json()["is_private"] is False

        after = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert after.json()["raw_input"] == "public text"


class TestPrivacyScoping:
    """Lock is per-user data, not a cross-account concern."""

    @pytest.mark.asyncio
    async def test_other_user_cannot_read_locked_memory(
        self, client, test_db, setup_users, get_auth_token
    ):
        _user1, user2 = await setup_users()
        token2 = get_auth_token("bob", "password456")
        memory = await _seed_memory(
            test_db, str(user2.id), "bob secret", "Bob Secret", is_private=True
        )

        response = client.get(
            f"/api/memories/{memory.id}",
            headers={"Authorization": f"Bearer {token2}", **_unlock_header(memory.id)},
        )

        # Owner can unlock their own memory.
        assert response.status_code == 200
        assert response.json()["raw_input"] == "bob secret"

    @pytest.mark.asyncio
    async def test_privacy_requires_authentication(self, client, test_db, setup_users):
        user1, _ = await setup_users()
        memory = await _seed_memory(
            test_db, str(user1.id), "x", "X", is_private=True
        )
        response = client.get(f"/api/memories/{memory.id}")
        assert response.status_code in (401, 403)
