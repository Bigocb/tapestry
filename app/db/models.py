"""SQLAlchemy ORM models for MEMIND."""

from sqlalchemy import (
    Column,
    String,
    Text,
    TIMESTAMP,
    UUID,
    Float,
    Integer,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator
import uuid

# Handle database-specific types
_using_postgres = True
try:
    from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

    STRUCTURED_CONTENT_TYPE = PG_JSONB
except ImportError:
    STRUCTURED_CONTENT_TYPE = JSON
    _using_postgres = False


# UUID type that works with SQLite (uses String(36))
class GUID(TypeDecorator):
    """Platform-independent GUID type that uses BINARY(16) on most platforms
    and VARCHAR(36) on SQLite."""

    impl = UUID
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(36))
        return dialect.type_descriptor(UUID())


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    memories = relationship(
        "Memory", back_populates="user", cascade="all, delete-orphan"
    )
    entities = relationship(
        "Entity", back_populates="user", cascade="all, delete-orphan"
    )
    stories = relationship("Story", back_populates="user", cascade="all, delete-orphan")


class Memory(Base):
    __tablename__ = "memories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Input & Raw Data
    raw_input = Column(Text, nullable=False)
    input_type = Column(String(50), nullable=False)  # 'voice', 'text', 'form'

    # Structured Content (Pydantic model serialized to JSON/JSONB)
    structured_content = Column(STRUCTURED_CONTENT_TYPE, nullable=True)

    # Embedding for semantic search (pgvector)
    embedding = Column(
        String(3000), nullable=True
    )  # Store as JSON string: can be NULL until enriched

    # Metadata
    # Note: ARRAY is Postgres-specific; SQLite will store as JSON
    tags = Column(
        ARRAY(String) if _using_postgres else JSON, default=list, nullable=False
    )
    mood = Column(String(50), nullable=True)
    importance_level = Column(Integer, default=5, nullable=False)  # 1-10

    # Processing state
    processing_state = Column(String(50), default="raw", nullable=False)
    # States: raw → capturing → refined → enriching → enriched → ready

    # Relationships
    # Note: ARRAY is Postgres-specific; SQLite will store as JSON
    related_memory_ids = Column(
        ARRAY(UUID) if _using_postgres else JSON, default=list, nullable=False
    )

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="memories")
    entities = relationship(
        "Entity", back_populates="memory", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_memories_user_id", "user_id"),
        Index("idx_memories_created_at", "created_at", postgresql_using="btree"),
        Index("idx_memories_tags", "tags", postgresql_using="gin"),
    )


class Entity(Base):
    __tablename__ = "entities"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    memory_id = Column(
        GUID(),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
    )

    type = Column(
        String(50), nullable=False
    )  # 'person', 'place', 'date', 'event', 'concept'
    value = Column(Text, nullable=False)
    entity_metadata = Column(STRUCTURED_CONTENT_TYPE, nullable=True)  # Extra info

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="entities")
    memory = relationship("Memory", back_populates="entities")

    # Indexes
    __table_args__ = (
        Index("idx_entities_user_id", "user_id"),
        Index("idx_entities_memory_id", "memory_id"),
    )


class Story(Base):
    __tablename__ = "stories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title = Column(String(255), nullable=False)
    narrative = Column(Text, nullable=False)
    memory_ids = Column(ARRAY(UUID) if _using_postgres else JSON, nullable=False)

    story_type = Column(
        String(50), nullable=True
    )  # 'chronological', 'thematic', 'curated', 'digest'

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="stories")

    # Indexes
    __table_args__ = (Index("idx_stories_user_id", "user_id"),)


class JobStatus(Base):
    __tablename__ = "job_status"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), nullable=False)
    memory_id = Column(GUID(), nullable=True)

    task_type = Column(
        String(50), nullable=False
    )  # 'refinement', 'enrichment', 'story'
    status = Column(
        String(50), nullable=False
    )  # 'pending', 'running', 'completed', 'failed'
    progress = Column(Float, default=0.0, nullable=False)  # 0-1
    error = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )
