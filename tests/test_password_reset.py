"""Tests for password reset (Issue 37).

There is no way back into an account whose password is lost, which is why the
operator of this instance once had to reset one by hand against the database.

The load-bearing rule throughout: the API must never return the token. The
moment it does, anyone who knows a username can take the account over, and the
usernames here are guessable.
"""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, get_db
from app.security import hash_password


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _no_smtp(monkeypatch):
    """Force the log path regardless of the host's environment.

    With SMTP configured the link is emailed, not logged, and these tests read
    it from the log. A developer's or the deployed .env must not change what the
    suite proves.
    """
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)


@pytest.fixture
async def test_db():
    from sqlalchemy.pool import StaticPool

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
def setup_users(test_db):
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


def link_from_log(caplog_text: str) -> str:
    """Pull the reset link out of the log, exactly as the operator would."""
    match = re.search(r"https?://\S*reset-password\?token=(\S+)", caplog_text)
    assert match, f"no reset link in the log:\n{caplog_text}"
    return match.group(1)


class TestRequestReset:
    async def test_a_request_creates_a_link_for_the_operator(
        self, client, setup_users, caplog
    ):
        await setup_users()

        response = client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )

        assert response.status_code == 200
        assert link_from_log(caplog.text)

    async def test_the_token_never_reaches_the_caller(
        self, client, setup_users, caplog
    ):
        await setup_users()

        response = client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )

        token = link_from_log(caplog.text)
        # Returning it would be an account-takeover hole, not a feature.
        assert token not in response.text

    async def test_an_unknown_account_answers_identically(
        self, client, setup_users
    ):
        await setup_users()

        known = client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        unknown = client.post(
            "/api/auth/forgot-password", json={"identifier": "nobody"}
        )

        # Otherwise the endpoint lists who has an account.
        assert known.status_code == unknown.status_code
        assert known.json() == unknown.json()

    async def test_an_email_address_works_too(self, client, setup_users, caplog):
        await setup_users()

        response = client.post(
            "/api/auth/forgot-password", json={"identifier": "alice@example.com"}
        )

        assert response.status_code == 200
        assert link_from_log(caplog.text)


class TestCompleteReset:
    async def test_a_valid_token_sets_the_new_password(
        self, client, setup_users, caplog
    ):
        await setup_users()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        token = link_from_log(caplog.text)

        response = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "brand-new-passphrase"},
        )

        assert response.status_code == 200
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "brand-new-passphrase"},
            ).status_code
            == 200
        )
        # The old one stops working.
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "alice", "password": "password123"},
            ).status_code
            == 401
        )

    async def test_a_token_cannot_be_used_twice(
        self, client, setup_users, caplog
    ):
        await setup_users()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        token = link_from_log(caplog.text)

        client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "first-new-passphrase"},
        )
        second = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "second-new-passphrase"},
        )

        assert second.status_code == 400

    async def test_an_expired_token_is_refused(
        self, client, setup_users, caplog, monkeypatch
    ):
        # A zero-minute lifetime, rather than waiting half an hour.
        monkeypatch.setenv("RESET_TOKEN_MINUTES", "0")
        await setup_users()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        token = link_from_log(caplog.text)

        response = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "brand-new-passphrase"},
        )

        assert response.status_code == 400

    async def test_completing_a_reset_invalidates_the_others(
        self, client, setup_users, caplog
    ):
        await setup_users()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        first = link_from_log(caplog.text)

        caplog.clear()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        second = link_from_log(caplog.text)

        client.post(
            "/api/auth/reset-password",
            json={"token": first, "new_password": "brand-new-passphrase"},
        )

        # The other outstanding link must not still work.
        stale = client.post(
            "/api/auth/reset-password",
            json={"token": second, "new_password": "another-passphrase"},
        )
        assert stale.status_code == 400

    async def test_repeated_requests_are_limited(
        self, client, setup_users, caplog
    ):
        await setup_users()

        links = 0
        for _ in range(5):
            caplog.clear()
            client.post(
                "/api/auth/forgot-password", json={"identifier": "alice"}
            )
            if "reset-password?token=" in caplog.text:
                links += 1

        # Three an hour is the default. Asked five times, three links.
        assert links == 3

    def test_the_link_is_emailed_when_smtp_is_configured(self, monkeypatch):
        sent: dict = {}

        class FakeSMTP:
            def __init__(self, host, port):
                sent["host"] = host

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def starttls(self):
                pass

            def login(self, user, password):
                pass

            def send_message(self, message):
                sent["to"] = message["To"]
                sent["body"] = message.get_content()

        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

        from app import reset

        emailed = reset.deliver(
            "someone@example.com", "http://app/reset-password?token=abc"
        )

        assert emailed is True
        assert sent["host"] == "smtp.example.com"
        assert sent["to"] == "someone@example.com"
        assert "token=abc" in sent["body"]

    def test_nothing_is_emailed_without_smtp(self, monkeypatch):
        monkeypatch.delenv("SMTP_HOST", raising=False)

        from app import reset

        # It reports what actually happened rather than implying a message went
        # out that never did.
        assert reset.deliver("someone@example.com", "http://app/x") is False

    async def test_a_weak_password_is_refused(self, client, setup_users, caplog):
        await setup_users()
        client.post(
            "/api/auth/forgot-password", json={"identifier": "alice"}
        )
        token = link_from_log(caplog.text)

        response = client.post(
            "/api/auth/reset-password",
            json={"token": token, "new_password": "short"},
        )

        assert response.status_code == 422
