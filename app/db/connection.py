"""Database connection and async session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import os
import warnings

DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./memind.db"
)

# Convert standard postgres:// to postgresql+psycopg:// for async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)


def _create_engine():
    """Create the async engine.

    Defaults to a local SQLite file for development so the app runs without
    Postgres. Set DATABASE_URL to a PostgreSQL connection string to use
    PostgreSQL/pgvector in production.
    """
    return create_async_engine(
        DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )


engine = _create_engine()

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """Dependency injection for async database session."""
    async with AsyncSessionLocal() as session:
        yield session
