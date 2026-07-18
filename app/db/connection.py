"""Database connection and async session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/memind"
)

# Convert standard postgres:// to postgresql+psycopg:// for async
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,  # For Render free tier, disable connection pooling
)

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
