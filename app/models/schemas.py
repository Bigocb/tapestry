"""Pydantic schemas for MEMIND API and data validation."""

from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
from typing import Optional, List, Union
from datetime import datetime
from uuid import UUID
import re


# ============================================================================
# USER MODELS
# ============================================================================


class UserCreate(BaseModel):
    """User registration request."""

    username: str = Field(..., min_length=3, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        """Username must be alphanumeric with underscores/hyphens only."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "username must contain only alphanumeric chars, underscores, or hyphens"
            )
        return v


class UserLogin(BaseModel):
    """User login request."""

    username: str
    password: str


class UserResponse(BaseModel):
    """User response (no password)."""

    id: UUID
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"


# ============================================================================
# ENTITY MODELS
# ============================================================================


class EntityData(BaseModel):
    """Entity extracted from a memory."""

    type: str = Field(..., description="'person', 'place', 'date', 'event', 'concept'")
    value: str = Field(..., description="Entity value/name")
    metadata: Optional[dict] = Field(
        None, description="Extra info (e.g., date format, person role)"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        """Type must be one of the allowed values."""
        allowed = ["person", "place", "date", "event", "concept"]
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v


class EntityResponse(EntityData):
    """Entity with ID (from database)."""

    id: UUID
    memory_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# MEMORY MODELS
# ============================================================================


class StructuredMemory(BaseModel):
    """Structured representation of a memory after capture/refinement."""

    title: str = Field(..., min_length=1, max_length=255)
    summary: str = Field(..., min_length=1)
    entities: List[EntityData] = Field(default_factory=list)
    mood: Optional[str] = None
    importance_level: int = Field(default=5, ge=1, le=10)
    initial_tags: List[str] = Field(default_factory=list)
    event_date: Optional[datetime] = Field(
        None, description="When the remembered event occurred (ISO 8601)"
    )
    date_precision: Optional[str] = Field(
        None,
        description="'exact' | 'month' | 'year' | 'decade' | 'range' | 'unknown'",
    )
    event_date_end: Optional[datetime] = Field(
        None, description="Upper bound when date_precision is 'range'"
    )
    date_label: Optional[str] = Field(
        None, description="Human wording for a fuzzy period, e.g. 'the 80s'"
    )

    @field_validator("date_precision")
    @classmethod
    def validate_date_precision(cls, v):
        if v is None:
            return v
        allowed = ["exact", "month", "year", "decade", "range", "unknown"]
        if v not in allowed:
            raise ValueError(f"date_precision must be one of {allowed}")
        return v


class MemoryCapture(BaseModel):
    """Input for capturing a new memory."""

    raw_input: str = Field(
        ...,
        min_length=1,
        description="Raw memory text (from voice transcription, text, or form)",
    )
    input_type: str = Field(..., description="'voice', 'text', or 'form'")

    @field_validator("input_type")
    @classmethod
    def validate_input_type(cls, v):
        allowed = ["voice", "text", "form"]
        if v not in allowed:
            raise ValueError(f"input_type must be one of {allowed}")
        return v


class MemoryResponse(BaseModel):
    """Complete memory response with all data."""

    id: UUID
    user_id: UUID
    raw_input: str
    input_type: str
    structured_content: Optional[Union[StructuredMemory, dict]] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    mood: Optional[str] = None
    importance_level: int = Field(default=5, ge=1, le=10)
    processing_state: str  # 'raw', 'refined', 'enriched', 'ready'
    related_memory_ids: List[UUID] = Field(default_factory=list)
    event_date: Optional[datetime] = None
    date_precision: Optional[str] = None
    event_date_end: Optional[datetime] = None
    date_label: Optional[str] = None
    people: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    needs_review: bool = False
    review_reason: Optional[str] = None
    is_private: bool = False
    is_locked: bool = Field(
        False,
        description="True when the memory is private and not unlocked for this session",
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemoryTextCapture(BaseModel):
    """Text-only memory capture request."""

    raw_input: str = Field(
        ...,
        min_length=1,
        description="Raw memory text from the user.",
    )


class MemoryFormCapture(BaseModel):
    """Structured form-based memory capture request."""

    raw_input: str = Field(
        ...,
        min_length=1,
        description="Raw memory text from the user.",
    )
    mood: Optional[str] = Field(None, description="Mood associated with the memory")
    tags: List[str] = Field(default_factory=list, description="Initial tags")
    people: List[str] = Field(default_factory=list, description="People mentioned")
    location: Optional[str] = Field(None, description="Location of the memory")
    importance_level: int = Field(default=5, ge=1, le=10)


class MemoryUpdate(BaseModel):
    """Update request for a memory.

    Unknown fields are rejected (``extra="forbid"``) rather than silently
    ignored. Pydantic's default is to drop them, which previously meant a
    frontend sending a misspelled field got a 200 while the edit vanished.
    """

    model_config = ConfigDict(extra="forbid")

    raw_input: Optional[str] = None
    structured_content: Optional[StructuredMemory] = None
    title: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = None
    tags: Optional[List[str]] = None
    mood: Optional[str] = None
    importance_level: Optional[int] = Field(None, ge=1, le=10)
    related_memory_ids: Optional[List[UUID]] = None
    event_date: Optional[datetime] = None
    date_precision: Optional[str] = None
    event_date_end: Optional[datetime] = None
    date_label: Optional[str] = None
    people: Optional[List[str]] = None
    location: Optional[str] = None
    is_private: Optional[bool] = None


# ============================================================================
# SEARCH MODELS
# ============================================================================


class SearchFilters(BaseModel):
    """Structured filters for memory search."""

    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None
    tags: Optional[List[str]] = Field(
        None, description="Filter by ANY of these tags (OR)"
    )
    mood: Optional[str] = None
    importance_min: Optional[int] = Field(None, ge=1, le=10)
    importance_max: Optional[int] = Field(None, ge=1, le=10)


class SearchQuery(BaseModel):
    """Structured search query (can come from natural language parsing or user input)."""

    text: Optional[str] = Field(None, description="Full-text search terms")
    semantic: Optional[str] = Field(None, description="Semantic search query")
    filters: Optional[SearchFilters] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    """Single search result."""

    memory_id: UUID
    title: Optional[str] = None
    summary: Optional[str] = None
    score: float = Field(..., description="Relevance score (0-1)")
    event_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    """Search response with multiple results."""

    results: List[SearchResult]
    total: int = Field(..., description="Total number of results (before pagination)")
    limit: int
    offset: int


# ============================================================================
# STORY MODELS
# ============================================================================


class StoryGenerate(BaseModel):
    """Request to generate a story."""

    memory_ids: List[UUID] = Field(
        ..., min_length=1, description="Memories to include in story"
    )
    story_type: str = Field(
        ..., description="'chronological', 'thematic', 'curated', or 'digest'"
    )
    custom_prompt: Optional[str] = Field(
        None, description="Optional custom prompt for tone/focus"
    )

    @field_validator("story_type")
    @classmethod
    def validate_story_type(cls, v):
        allowed = ["chronological", "thematic", "curated", "digest"]
        if v not in allowed:
            raise ValueError(f"story_type must be one of {allowed}")
        return v


class StoryResponse(BaseModel):
    """Generated story response."""

    id: UUID
    user_id: UUID
    title: str
    narrative: str = Field(..., description="Generated markdown narrative")
    memory_ids: List[UUID]
    story_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StoryExport(BaseModel):
    """Story export request."""

    format: str = Field(default="markdown", description="'markdown', 'txt', or 'json'")

    @field_validator("format")
    @classmethod
    def validate_format(cls, v):
        allowed = ["markdown", "txt", "json"]
        if v not in allowed:
            raise ValueError(f"format must be one of {allowed}")
        return v


# ============================================================================
# TIMELINE MODELS
# ============================================================================


class TimelineQuery(BaseModel):
    """Query parameters for timeline view."""

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: Optional[List[str]] = None
    mood: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


# ============================================================================
# INSIGHTS MODELS
# ============================================================================


class MemoryStats(BaseModel):
    """Statistics about memories."""

    total_memories: int
    memories_by_mood: dict = Field(default_factory=dict, description="Count by mood")
    memories_by_tag: dict = Field(default_factory=dict, description="Count by tag")
    average_importance: float


class TrendData(BaseModel):
    """Data point for trends."""

    timestamp: datetime
    value: float


class MemoryTrends(BaseModel):
    """Trends over time."""

    memories_per_week: List[TrendData]
    mood_trend: List[TrendData] = Field(
        default_factory=list, description="Average mood per week"
    )


class WordCloudData(BaseModel):
    """Word cloud data."""

    word: str
    frequency: int


class Achievement(BaseModel):
    """User achievement/badge."""

    id: str = Field(..., description="Unique achievement ID")
    name: str
    description: str
    earned: bool
    progress: Optional[float] = Field(
        None, description="0-1 progress toward achievement"
    )


class InsightsResponse(BaseModel):
    """Complete insights dashboard response."""

    stats: MemoryStats
    trends: MemoryTrends
    word_cloud: List[WordCloudData]
    achievements: List[Achievement]
    streak_days: int = Field(default=0, description="Consecutive days with captures")


# ============================================================================
# REVIEW QUEUE MODELS
# ============================================================================


class ReviewQueueResponse(BaseModel):
    """A page of memories awaiting user review."""

    items: List[MemoryResponse]
    total: int = Field(..., description="Total memories needing review")
    limit: int
    offset: int


# ============================================================================
# ENTITY READ MODELS (first-class people/places/organizations)
# ============================================================================


class EntitySummary(BaseModel):
    """An entity as shown in a list (people/places browse)."""

    id: UUID
    kind: str  # 'person' | 'place' | 'organization'
    canonical_name: str
    description: Optional[str] = None
    attributes: Optional[dict] = None
    parent_entity_id: Optional[UUID] = None
    # Number of *visible* (unlocked) memories mentioning this entity.
    mention_count: int = 0
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EntityListResponse(BaseModel):
    """A page of entities."""

    items: List[EntitySummary]
    total: int
    limit: int
    offset: int


class EntityMemoryRef(BaseModel):
    """A memory that mentions an entity, as listed on the entity page."""

    id: UUID
    title: Optional[str] = None
    summary: Optional[str] = None
    role: Optional[str] = Field(
        None, description="How the entity was referred to in this memory"
    )
    event_date: Optional[datetime] = None
    date_precision: Optional[str] = None
    date_label: Optional[str] = None
    created_at: datetime


class EntityDetail(EntitySummary):
    """Full entity, including every spelling and the memories mentioning it."""

    aliases: List[str] = Field(default_factory=list)
    memories: List[EntityMemoryRef] = Field(default_factory=list)


class EntityMergeRequest(BaseModel):
    """Merge one entity into another."""

    source_id: UUID = Field(..., description="Entity to fold away")
    target_id: UUID = Field(..., description="Entity to keep")


class EntityMergeResponse(BaseModel):
    """Result of a merge, including the audit id needed to undo it."""

    merge_id: UUID
    source_id: UUID
    target_id: UUID
    moved_mention_count: int
    moved_alias_count: int


class EntityMergeSuggestion(BaseModel):
    """A pair of entities that may be the same thing, for the user to confirm."""

    source: EntitySummary
    target: EntitySummary
    reason: str = Field(..., description="Why these were suggested")


# ============================================================================
# RELATED MEMORY MODELS
# ============================================================================


class RelatedMemory(BaseModel):
    """A memory that shares entities with another, and what is shared."""

    id: UUID
    title: Optional[str] = None
    summary: Optional[str] = None
    event_date: Optional[datetime] = None
    date_precision: Optional[str] = None
    date_label: Optional[str] = None
    created_at: datetime
    shared_entities: List[str] = Field(default_factory=list)
    shared_count: int = 0


class RelatedMemoriesResponse(BaseModel):
    """Related memories for one memory."""

    items: List[RelatedMemory]
    total: int


# ============================================================================
# JOB STATUS MODELS
# ============================================================================


class JobStatusResponse(BaseModel):
    """Async job status."""

    job_id: UUID
    task_type: str  # 'refinement', 'enrichment', 'story'
    status: str  # 'pending', 'running', 'completed', 'failed'
    progress: float = Field(ge=0, le=1)
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ERROR MODELS
# ============================================================================


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
    status_code: int = 400


# ============================================================================
# TELLING MODELS
# ============================================================================


class TellingCreate(BaseModel):
    """A recounting submitted for segmentation."""

    raw_transcript: str = Field(..., min_length=1, max_length=20000)


class TellingSegmentResponse(BaseModel):
    """A proposed memory cut from a telling, awaiting review."""

    id: UUID
    ordinal: int
    text: str
    status: str
    title: Optional[str] = None
    summary: Optional[str] = None
    structured_content: Optional[dict] = None
    event_date: Optional[datetime] = None
    date_precision: Optional[str] = None
    event_date_end: Optional[datetime] = None
    date_label: Optional[str] = None
    memory_id: Optional[UUID] = None

    class Config:
        from_attributes = True


class TellingSegmentUpdate(BaseModel):
    """Edits to a proposed segment, applied before it is committed.

    A resolved date is the cursor's best answer, not the last word, so the user
    can correct it. Only fields actually sent are applied — an explicit null
    clears one, and an omitted field is left alone.
    """

    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(None, min_length=1, max_length=20000)
    title: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = None
    status: Optional[str] = None

    event_date: Optional[datetime] = None
    event_date_end: Optional[datetime] = None
    date_precision: Optional[str] = None
    date_label: Optional[str] = Field(None, max_length=120)


class TellingResponse(BaseModel):
    """A telling together with its proposed split."""

    id: UUID
    raw_transcript: str
    input_type: str
    status: str
    error: Optional[str] = None
    frame_date: Optional[datetime] = None
    frame_label: Optional[str] = None
    created_at: datetime
    segments: List[TellingSegmentResponse] = []

    class Config:
        from_attributes = True
