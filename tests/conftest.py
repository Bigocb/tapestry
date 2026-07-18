"""Pytest configuration and shared fixtures."""

import pytest
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set test database URL to avoid loading Postgres during tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
