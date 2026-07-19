"""Database connection and async session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import os
import warnings

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/memind"
)

# Convert standard postgres:// to postgresql+psycopg:// for async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)


def _create_engine():
    """Create the async engine, falling back to SQLite if Postgres is unavailable.

    On local Windows development machines without libpq, the psycopg driver may
    fail to import. We fall back to an in-memory SQLite database so that routes
    that do not require Postgres (such as the wiki viewer) can still start.
    """
    if DATABASE_URL.startswith("postgresql"):
        try:
            return create_async_engine(
                DATABASE_URL,
                echo=False,
                poolclass=NullPool,  # For Render free tier, disable connection pooling
            )
        except ImportError as exc:
            warnings.warn(
                f"Postgres driver unavailable ({exc}). Falling back to SQLite. "
                "Set DATABASE_URL to a valid connection string to use PostgreSQL.",
                RuntimeWarning,
                stacklevel=2,
            )
            return create_async_engine(
                "sqlite+aiosqlite:///:memory:",
                echo=False,
                poolclass=NullPool,
            )

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
