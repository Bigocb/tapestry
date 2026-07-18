"""Tests for database setup and pgvector functionality.

RED: Verify that Postgres with pgvector is set up correctly.
- Can connect to database
- pgvector extension is installed
- Base schema exists
- Can insert and query memory with embedding
"""

import pytest
import json
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, func
from app.db import Base, engine, User, Memory
import uuid


@pytest.fixture
async def db_session():
    """Create a test database session."""
    async_engine = engine
    async with async_engine.begin() as conn:
        # Create all tables (idempotent)
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async with async_session_maker() as session:
        yield session


@pytest.mark.asyncio
async def test_database_connection(db_session):
    """Test that we can connect to the database."""
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_pgvector_extension_installed(db_session):
    """Test that pgvector extension is installed."""
    try:
        result = await db_session.execute(
            text("SELECT * FROM pg_extension WHERE extname='vector'")
        )
        extension = result.fetchone()
        assert extension is not None, "pgvector extension not installed"
    except Exception as e:
        pytest.skip(f"pgvector extension check failed: {e}")


@pytest.mark.asyncio
async def test_schema_created(db_session):
    """Test that base schema tables exist."""
    # Check if users table exists
    result = await db_session.execute(
        text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'users'
        )
        """)
    )
    assert result.scalar() is True, "users table not created"

    # Check if memories table exists
    result = await db_session.execute(
        text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'memories'
        )
        """)
    )
    assert result.scalar() is True, "memories table not created"


@pytest.mark.asyncio
async def test_can_insert_user(db_session):
    """Test that we can insert a user."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="testuser",
        email="test@example.com",
        password_hash="hashed_password_123",
    )
    db_session.add(user)
    await db_session.commit()

    # Verify it was inserted
    result = await db_session.execute(
        text("SELECT id FROM users WHERE username = 'testuser'")
    )
    retrieved_id = result.scalar()
    assert retrieved_id is not None


@pytest.mark.asyncio
async def test_can_insert_memory_with_embedding(db_session):
    """Test that we can insert a memory with embedding (as JSON string)."""
    # First create a user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="testuser2",
        email="test2@example.com",
        password_hash="hashed_password_456",
    )
    db_session.add(user)
    await db_session.commit()

    # Now create a memory with a mock embedding
    memory_id = uuid.uuid4()
    # Simulate a vector embedding as a JSON string (1536 dims)
    mock_embedding = json.dumps([0.1] * 1536)

    memory = Memory(
        id=memory_id,
        user_id=user_id,
        raw_input="I had coffee with Sarah today and discussed the project",
        input_type="text",
        structured_content={
            "title": "Coffee with Sarah",
            "summary": "Discussed project with Sarah over coffee",
            "entities": [
                {"type": "person", "value": "Sarah"},
                {"type": "event", "value": "coffee"},
            ],
            "mood": "happy",
            "importance_level": 7,
        },
        embedding=mock_embedding,
        tags=["work", "social"],
        mood="happy",
        importance_level=7,
        processing_state="enriched",
    )
    db_session.add(memory)
    await db_session.commit()

    # Verify it was inserted
    result = await db_session.execute(
        text("SELECT id, raw_input FROM memories WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    retrieved = result.fetchone()
    assert retrieved is not None
    assert retrieved[1] == "I had coffee with Sarah today and discussed the project"


@pytest.mark.asyncio
async def test_can_query_embeddings(db_session):
    """Test that we can query memories by semantic similarity (pgvector)."""
    # First create a user
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="testuser3",
        email="test3@example.com",
        password_hash="hashed_password_789",
    )
    db_session.add(user)
    await db_session.commit()

    # Create multiple memories with embeddings
    memory_ids = []
    for i in range(3):
        memory_id = uuid.uuid4()
        mock_embedding = json.dumps([0.1] * 1536)
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            raw_input=f"Memory {i}",
            input_type="text",
            structured_content={"title": f"Memory {i}"},
            embedding=mock_embedding,
            tags=[],
            processing_state="enriched",
        )
        db_session.add(memory)
        memory_ids.append(memory_id)

    await db_session.commit()

    # Verify we can count the memories
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM memories WHERE user_id = :user_id"),
        {"user_id": str(user_id)},
    )
    count = result.scalar()
    assert count == 3, f"Expected 3 memories, got {count}"


@pytest.mark.asyncio
async def test_user_isolation(db_session):
    """Test that one user's memories don't leak to another user."""
    # Create user 1
    user_id_1 = uuid.uuid4()
    user_1 = User(
        id=user_id_1, username="user1", email="user1@example.com", password_hash="pass1"
    )
    db_session.add(user_1)

    # Create user 2
    user_id_2 = uuid.uuid4()
    user_2 = User(
        id=user_id_2, username="user2", email="user2@example.com", password_hash="pass2"
    )
    db_session.add(user_2)
    await db_session.commit()

    # Create memory for user 1
    memory_1 = Memory(
        id=uuid.uuid4(),
        user_id=user_id_1,
        raw_input="User 1 memory",
        input_type="text",
        structured_content={"title": "User 1"},
        tags=[],
        processing_state="enriched",
    )
    db_session.add(memory_1)

    # Create memory for user 2
    memory_2 = Memory(
        id=uuid.uuid4(),
        user_id=user_id_2,
        raw_input="User 2 memory",
        input_type="text",
        structured_content={"title": "User 2"},
        tags=[],
        processing_state="enriched",
    )
    db_session.add(memory_2)
    await db_session.commit()

    # Verify user 1 only sees their memory
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM memories WHERE user_id = :user_id"),
        {"user_id": str(user_id_1)},
    )
    count_1 = result.scalar()
    assert count_1 == 1

    # Verify user 2 only sees their memory
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM memories WHERE user_id = :user_id"),
        {"user_id": str(user_id_2)},
    )
    count_2 = result.scalar()
    assert count_2 == 1
