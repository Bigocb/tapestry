"""Pytest configuration and shared fixtures."""

import pytest
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
