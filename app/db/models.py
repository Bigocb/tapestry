"""SQLAlchemy ORM models for MEMIND."""

from sqlalchemy import (
    Column,
    String,
    Text,
    TIMESTAMP,
    UUID,
    Float,
    Integer,
    Boolean,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator
import uuid


# Handle database-specific types (JSON vs JSONB)
class DBJSON(TypeDecorator):
    """JSON type that uses JSONB on Postgres, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


STRUCTURED_CONTENT_TYPE = DBJSON()


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

    def process_bind_param(self, value, dialect):
        """Convert UUID to string for SQLite."""
        if value is None:
            return value
        if dialect.name == "sqlite":
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        """Convert string back to UUID."""
        if value is None:
            return value
        from uuid import UUID as UUID_TYPE

        if isinstance(value, UUID_TYPE):
            return value
        return UUID_TYPE(value)


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
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Input & Raw Data
    raw_input = Column(Text, nullable=False)
    input_type = Column(String(50), nullable=False)  # 'voice', 'text', 'form'

    # Structured Content (Pydantic model serialized to JSON/JSONB)
    structured_content = Column(STRUCTURED_CONTENT_TYPE, nullable=True)

    # Embedding for semantic search, serialized to a JSON string by
    # ``serialize_embedding``. NULL until enriched.
    #
    # This must stay unbounded: a 1024-dimension vector serialises to roughly
    # 8.6 kB. It used to be VARCHAR(3000), which SQLite never enforced, so the
    # overflow only surfaced once the data moved to Postgres.
    embedding = Column(Text, nullable=True)

    # Metadata
    # Note: Use DBJSON for cross-database compatibility
    tags = Column(DBJSON(), default=list, nullable=False)
    mood = Column(String(50), nullable=True)
    importance_level = Column(Integer, default=5, nullable=False)  # 1-10

    # Processing state
    processing_state = Column(String(50), default="raw", nullable=False)
    # States: raw → capturing → refined → enriching → enriched → ready

    # Relationships
    # Note: Use DBJSON for cross-database compatibility
    related_memory_ids = Column(DBJSON(), default=list, nullable=False)

    # When the remembered event occurred (extracted from raw_input by agents)
    event_date = Column(TIMESTAMP, nullable=True)

    # How precise that date is. 'exact' | 'month' | 'year' | 'decade' |
    # 'range' | 'unknown'. A fuzzy period (e.g. "the 80s") is still a real
    # answer, so it must not be treated as a missing date.
    date_precision = Column(String(20), nullable=True)
    # Upper bound when date_precision == 'range' (e.g. 1987-1990).
    event_date_end = Column(TIMESTAMP, nullable=True)
    # Human wording for fuzzy periods, shown instead of a fake exact date,
    # e.g. "Middle school", "the 80s", "early 90s".
    date_label = Column(String(120), nullable=True)

    # Review queue: set when the pipeline could not confidently complete
    # (currently: no event date could be found). review_reason is a short
    # machine-readable code, e.g. 'missing_date'.
    needs_review = Column(Boolean, default=False, nullable=False)
    review_reason = Column(String(50), nullable=True)

    # Privacy screen: a private memory's content is withheld from every API
    # response until the client explicitly unlocks it for the session.
    is_private = Column(Boolean, default=False, nullable=False)

    # Migration marker: the one-time entity backfill has processed this row.
    entities_backfilled = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="memories")
    entity_mentions = relationship(
        "MemoryEntity", back_populates="memory", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_memories_user_id", "user_id"),
        Index("idx_memories_created_at", "created_at", postgresql_using="btree"),
        Index("idx_memories_tags", "tags", postgresql_using="gin"),
    )


class Entity(Base):
    """A canonical person, place or organization.

    Distinct from a *mention*: this is the real-world thing, one row per
    person/place/org regardless of how many times or ways it is named. See
    ``MemoryEntity`` for occurrences and ``EntityAlias`` for spellings.
    """

    __tablename__ = "entities"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    kind = Column(String(20), nullable=False)  # 'person' | 'place' | 'organization'
    canonical_name = Column(String(255), nullable=False)
    # Matching key (lowercased, whitespace collapsed, possessives stripped).
    normalized_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Kind-specific extras: {relation, born} | {address, lat, lon} | {domain}.
    attributes = Column(DBJSON(), nullable=True)

    # Containment hierarchy, e.g. "Bluebird Cafe" -> "Denver".
    parent_entity_id = Column(
        GUID(), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )

    # Denormalized for fast ranking; recomputed from mentions.
    mention_count = Column(Integer, default=0, nullable=False)
    first_seen_at = Column(TIMESTAMP, nullable=True)
    last_seen_at = Column(TIMESTAMP, nullable=True)

    # Non-null means this entity was merged into another and is a tombstone.
    # Queries must filter merged_into_id IS NULL.
    merged_into_id = Column(
        GUID(), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="entities")
    aliases = relationship(
        "EntityAlias", back_populates="entity", cascade="all, delete-orphan"
    )
    mentions = relationship(
        "MemoryEntity", back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_entities_user_kind", "user_id", "kind"),
        Index("idx_entities_user_norm_name", "user_id", "normalized_name"),
        Index("idx_entities_parent", "parent_entity_id"),
        Index("idx_entities_user_mentions", "user_id", "mention_count"),
    )


class EntityAlias(Base):
    """One way an entity's name has been written.

    ``(user_id, normalized_alias)`` is unique: an alias resolves to exactly one
    entity, which is what makes exact-match auto-linking safe.
    """

    __tablename__ = "entity_aliases"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(
        GUID(), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )

    alias = Column(String(255), nullable=False)
    normalized_alias = Column(String(255), nullable=False)
    # Copied from the entity so kind participates in uniqueness: a person
    # named "Paris" and the city "Paris" must be able to coexist.
    kind = Column(String(20), nullable=False)
    source = Column(String(20), nullable=False, default="llm")  # 'llm' | 'user'

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="aliases")

    __table_args__ = (
        Index(
            "idx_entity_aliases_user_kind_norm",
            "user_id",
            "kind",
            "normalized_alias",
            unique=True,
        ),
        Index("idx_entity_aliases_entity", "entity_id"),
    )


class MemoryEntity(Base):
    """A single mention of an entity inside a memory."""

    __tablename__ = "memory_entities"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    memory_id = Column(
        GUID(), ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    entity_id = Column(
        GUID(), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )

    # Exactly what was written here (may differ from the canonical name).
    surface_form = Column(String(255), nullable=False)
    role = Column(String(50), nullable=True)  # "wife", "brother", "venue"
    snippet = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    entity = relationship("Entity", back_populates="mentions")
    memory = relationship("Memory", back_populates="entity_mentions")

    __table_args__ = (
        Index("idx_memory_entities_entity", "entity_id"),
        Index("idx_memory_entities_memory", "memory_id"),
        Index("idx_memory_entities_user_entity", "user_id", "entity_id"),
    )


class EntityMerge(Base):
    """Audit record of an entity merge, so it can be reversed exactly."""

    __tablename__ = "entity_merges"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_entity_id = Column(GUID(), nullable=False)
    target_entity_id = Column(GUID(), nullable=False)

    # Exact ids moved, so an undo can put them back precisely.
    moved_mention_ids = Column(DBJSON(), default=list, nullable=False)
    moved_alias_ids = Column(DBJSON(), default=list, nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_entity_merges_user", "user_id"),)


class EntitySplit(Base):
    """Audit record of a split, so it can be reversed exactly.

    The counterpart to ``EntityMerge``. A merge is undone by moving recorded
    rows back and clearing a tombstone; a split is undone by moving recorded
    rows back and dropping the entity that only existed because of it.
    """

    __tablename__ = "entity_splits"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    source_entity_id = Column(GUID(), nullable=False)
    new_entity_id = Column(GUID(), nullable=False)

    moved_mention_ids = Column(DBJSON(), default=list, nullable=False)
    moved_alias_ids = Column(DBJSON(), default=list, nullable=False)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_entity_splits_user", "user_id"),)


class Story(Base):
    __tablename__ = "stories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(255), nullable=False)
    narrative = Column(Text, nullable=False)
    memory_ids = Column(DBJSON(), nullable=False)

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

    # User edits captured at the time the job was queued. Applied after the
    # agents run so an explicit correction is not clobbered by derived output.
    overrides = Column(DBJSON(), nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EntityFact(Base):
    """A fact found outside the app, held apart from what the user said.

    Deliberately its own table rather than entries in ``entities.attributes``.
    A looked-up fact must never be mistaken for the user's own recollection, and
    the way to guarantee that is to keep it somewhere else, labelled with where
    it came from and when it was fetched.
    """

    __tablename__ = "entity_facts"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(
        GUID(), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )

    source = Column(String(50), nullable=False)  # "wikidata"
    source_id = Column(String(100), nullable=False)  # "Q43096397"
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_url = Column(String(500), nullable=True)
    # Room for an entity's claims later without a migration.
    data = Column(DBJSON(), nullable=True)

    fetched_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_entity_facts_entity", "entity_id"),
        Index("idx_entity_facts_user", "user_id"),
    )


class PasswordResetToken(Base):
    """A single-use, short-lived token for choosing a new password.

    Stored **hashed**. The raw value is shown once, to the operator, and a
    stolen database should not hand anyone a working link. A plain hash is
    right here where bcrypt would not be: the token is 32 bytes of randomness,
    so there is nothing to brute-force.
    """

    __tablename__ = "password_reset_tokens"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    token_hash = Column(String(64), nullable=False, index=True)
    expires_at = Column(TIMESTAMP, nullable=False)
    # Non-null means it has been spent, successfully or not.
    used_at = Column(TIMESTAMP, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_password_reset_user", "user_id"),)


class Telling(Base):
    """One act of recounting.

    A telling owns the transcript and nothing else. Its segments are *proposed*
    memories; they become real ``Memory`` rows only when the user commits, so a
    draft can never leak into the timeline, search, or the entity graph.
    """

    __tablename__ = "tellings"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    raw_transcript = Column(Text, nullable=False)
    input_type = Column(String(20), nullable=False, default="text")
    # transcribing | segmenting | draft | committed | failed
    status = Column(String(20), nullable=False, default="draft")
    error = Column(Text, nullable=True)

    # Telling-wide fallback for segments with no date signal of their own.
    frame_date = Column(TIMESTAMP, nullable=True)
    frame_label = Column(String(120), nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    segments = relationship(
        "TellingSegment",
        back_populates="telling",
        cascade="all, delete-orphan",
        order_by="TellingSegment.ordinal",
    )

    __table_args__ = (
        Index("idx_tellings_user_status", "user_id", "status"),
        Index("idx_tellings_user_created", "user_id", "created_at"),
    )


class TellingSegment(Base):
    """A proposed memory cut from a telling.

    Deliberately not a ``Memory`` row with a draft flag: that would force every
    existing read path to learn to exclude drafts, and would let entity sync
    mint real entities from a split the user then discards.
    """

    __tablename__ = "telling_segments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    telling_id = Column(
        GUID(), ForeignKey("tellings.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    ordinal = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    # Same shape as ``memories.structured_content``, resolved once on the way in.
    structured_content = Column(STRUCTURED_CONTENT_TYPE, nullable=True)

    event_date = Column(TIMESTAMP, nullable=True)
    date_precision = Column(String(20), nullable=True)
    event_date_end = Column(TIMESTAMP, nullable=True)
    date_label = Column(String(120), nullable=True)

    # proposed | accepted | rejected
    status = Column(String(20), nullable=False, default="proposed")
    # Set at commit; links the created memory back to its segment.
    memory_id = Column(
        GUID(), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    telling = relationship("Telling", back_populates="segments")

    __table_args__ = (
        Index("idx_telling_segments_telling", "telling_id", "ordinal"),
        Index("idx_telling_segments_user", "user_id"),
        Index("idx_telling_segments_memory", "memory_id"),
    )
