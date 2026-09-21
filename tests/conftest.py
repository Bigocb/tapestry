"""Pytest configuration and shared fixtures."""

import pytest
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set test database URL to avoid loading Postgres during tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Engine tracking to prevent pytest from hanging at interpreter shutdown.
#
# aiosqlite runs each connection on a *non-daemon* worker thread. If a test
# engine is never disposed, that thread blocks forever on its queue and the
# Python interpreter waits for it during shutdown — tests pass, but pytest
# never exits. We wrap create_async_engine so every engine created in tests is
# registered, then dispose them all at session teardown.
# ---------------------------------------------------------------------------
import sqlalchemy.ext.asyncio as _sa_asyncio

_created_engines: list = []
_original_create_async_engine = _sa_asyncio.create_async_engine


def _tracking_create_async_engine(*args, **kwargs):
    engine = _original_create_async_engine(*args, **kwargs)
    _created_engines.append(engine)
    return engine


_sa_asyncio.create_async_engine = _tracking_create_async_engine


@pytest.fixture(scope="session", autouse=True)
def _dispose_engines_at_session_end():
    """Dispose every async engine created during the test session."""
    yield
    if not _created_engines:
        return

    loop = asyncio.new_event_loop()
    try:
        for engine in _created_engines:
            try:
                loop.run_until_complete(engine.dispose())
            except Exception:
                pass
    finally:
        loop.close()
        _created_engines.clear()


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
