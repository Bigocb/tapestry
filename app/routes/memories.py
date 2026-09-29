"""Memory capture and retrieval routes.

Routes for capturing, retrieving, updating, and deleting memories.
Includes support for voice, text, and form inputs.
"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from uuid import UUID
import uuid

from app.db import get_db, Memory, User, as_utc
from app.agents.capture import structure_memory
from app.agents.embeddings import (
    cosine_similarity,
    deserialize_embedding,
    generate_embedding,
)
from app.agents.search import parse_search_query
from app.jobs import scheduler as scheduler_module
from app.jobs.scheduler import create_job_status, schedule_job
from app.models.schemas import (
    MemoryCapture,
    MemoryResponse,
    MemoryTextCapture,
    MemoryFormCapture,
    MemoryUpdate,
    SearchFilters,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from app.dependencies import get_current_user
from app.privacy import LOCKED_SUMMARY, LOCKED_TITLE, get_unlocked_memory_ids, is_locked
from app.db.entities import (
    entity_ids_for_memory,
    recompute_entity_stats,
    sync_memory_entities,
)

router = APIRouter()

def get_background_session_factory():
    """Return the current background task session factory.

    Override point for tests so background tasks share the test database.
    """
    return scheduler_module.BackgroundSessionLocal



async def _schedule_refinement(
    memory_id: str, user_id: str, overrides: dict | None = None
) -> None:
    """Queue refinement and enrichment jobs for a captured memory.

    Uses APScheduler to run the agent pipeline asynchronously after the
    capture endpoint returns. A JobStatus row is created for each stage so
    progress and errors are observable.

    ``overrides`` carries user edits that must be re-applied after the agents
    run, so reprocessing a text edit does not clobber manual corrections.

    When the scheduler is not running (e.g. under TestClient, which does not
    run the FastAPI lifespan), the job is executed inline instead so tests
    observe completed job status. We never do both, otherwise the job would
    run twice and the two runs would race on the same memory row.
    """
    from app.jobs.worker import run_tracked_job

    session_factory = get_background_session_factory()
    async with session_factory() as db:
        # Create tracked refinement job.
        refinement_job = await create_job_status(
            db=db,
            user_id=user_id,
            memory_id=memory_id,
            task_type="refinement",
            status="pending",
            overrides=overrides,
        )

        if scheduler_module.scheduler.running:
            schedule_job(str(refinement_job.id))
        else:
            await run_tracked_job(str(refinement_job.id))


async def _transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio bytes to text.

    Default implementation is a placeholder that raises an informative error
    unless a transcription backend is configured. Override this function in
    tests or configure a real provider (e.g. Ollama Whisper) in production.
    """
    raise HTTPException(
        status_code=501,
        detail="Voice transcription is not configured. Set up a transcription backend.",
    )


def _extract_people_and_location(structured_content: dict | None) -> tuple[list[str], str | None]:
    """Pull people/location from structured entities and legacy form-only fields."""
    if not isinstance(structured_content, dict):
        return [], None

    people = set()
    location = None

    for entity in structured_content.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("type")
        value = entity.get("value")
        if entity_type == "person" and value:
            people.add(str(value))
        elif entity_type == "place" and value and location is None:
            location = str(value)

    # Legacy form-only fields win over entity inference.
    if structured_content.get("people"):
        people = {str(p) for p in structured_content["people"] if p}
    if structured_content.get("location"):
        location = str(structured_content["location"]) or None

    return sorted(people), location


def _apply_memory_date_fields(memory: Memory, structured) -> None:
    """Copy resolved date fields from a StructuredMemory onto the row.

    Keeps event_date, precision, range end and label together so a fuzzy
    period survives persistence instead of being flattened to a single day.
    """
    memory.event_date = structured.event_date
    memory.date_precision = getattr(structured, "date_precision", None)
    memory.event_date_end = getattr(structured, "event_date_end", None)
    memory.date_label = getattr(structured, "date_label", None)


def _apply_review_flags(memory: Memory) -> None:
    """Flag a memory for the review queue when the pipeline couldn't complete.

    A missing event date is the current reason: without one the memory cannot
    be placed on the timeline. A fuzzy period (decade, range, named life
    period) is a real answer, not a missing one, so a dated-but-fuzzy memory is
    NOT sent to review.
    """
    has_time_signal = (
        memory.event_date is not None
        or memory.date_precision in ("decade", "range")
        or bool(memory.date_label)
    )
    if has_time_signal:
        memory.needs_review = False
        memory.review_reason = None
    else:
        memory.needs_review = True
        memory.review_reason = "missing_date"


def _memory_response(
    memory: Memory, unlocked_ids: set[str] | None = None
) -> MemoryResponse:
    """Convert a Memory ORM object to a MemoryResponse Pydantic model.

    When the memory is private and has not been unlocked for this session, all
    content-bearing fields are withheld. Metadata needed to render the lock
    (id, dates, importance, lock state) is still returned so the UI can show a
    placeholder and an unlock control.
    """
    locked = is_locked(memory, unlocked_ids or set())

    if locked:
        return MemoryResponse(
            id=memory.id,
            user_id=memory.user_id,
            raw_input="",
            input_type=memory.input_type,
            structured_content=None,
            title=LOCKED_TITLE,
            summary=LOCKED_SUMMARY,
            tags=[],
            mood=None,
            importance_level=memory.importance_level,
            processing_state=memory.processing_state,
            related_memory_ids=[],
            event_date=memory.event_date,
            date_precision=memory.date_precision,
            event_date_end=memory.event_date_end,
            date_label=memory.date_label,
            people=[],
            location=None,
            needs_review=bool(memory.needs_review),
            review_reason=memory.review_reason,
            is_private=True,
            is_locked=True,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    content = memory.structured_content if isinstance(memory.structured_content, dict) else {}
    people, location = _extract_people_and_location(content)

    return MemoryResponse(
        id=memory.id,
        user_id=memory.user_id,
        raw_input=memory.raw_input,
        input_type=memory.input_type,
        structured_content=memory.structured_content,
        title=content.get("title"),
        summary=content.get("summary"),
        tags=memory.tags,
        mood=memory.mood,
        importance_level=memory.importance_level,
        processing_state=memory.processing_state,
        related_memory_ids=memory.related_memory_ids,
        event_date=memory.event_date,
        date_precision=memory.date_precision,
        event_date_end=memory.event_date_end,
        date_label=memory.date_label,
        people=people,
        location=location,
        needs_review=bool(memory.needs_review),
        review_reason=memory.review_reason,
        is_private=bool(memory.is_private),
        is_locked=False,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


async def _create_memory(
    db: AsyncSession,
    user: User,
    raw_input: str,
    input_type: str,
    mood: str | None = None,
    tags: list[str] | None = None,
    importance_level: int = 5,
) -> Memory:
    """Create and persist a Memory record with state='raw'."""
    memory = Memory(
        user_id=user.id,
        raw_input=raw_input,
        input_type=input_type,
        processing_state="raw",
        tags=tags or [],
        related_memory_ids=[],
        mood=mood,
        importance_level=importance_level,
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


async def _structure_and_update_memory(
    db: AsyncSession,
    memory: Memory,
    override_mood: str | None = None,
    override_tags: list[str] | None = None,
    override_importance: int | None = None,
    override_people: list[str] | None = None,
    override_location: str | None = None,
) -> None:
    """Run the Capture Agent and store the result on the memory row.

    User-provided metadata wins over agent output. The row is refreshed before
    this call, so the session already contains the latest state.
    """
    structured = await structure_memory(memory.raw_input)

    # User-provided values take precedence.
    if override_mood:
        structured.mood = override_mood
    if override_importance is not None:
        structured.importance_level = override_importance
    if override_tags:
        structured.initial_tags = override_tags

    memory.structured_content = structured.model_dump(mode="json")

    # Update denormalized top-level fields for querying/filtering.
    memory.mood = structured.mood
    memory.importance_level = structured.importance_level
    memory.tags = structured.initial_tags
    _apply_memory_date_fields(memory, structured)

    # Merge form-only fields (people, location) into structured_content.
    existing = memory.structured_content or {}
    if override_people:
        existing["people"] = override_people
    if override_location:
        existing["location"] = override_location
    memory.structured_content = existing

    memory.processing_state = "capturing"
    _apply_review_flags(memory)

    # Attach first-class entities so people/places are queryable immediately,
    # before the async pipeline runs.
    await sync_memory_entities(
        db, str(memory.user_id), str(memory.id), memory.structured_content
    )

    await db.commit()
    await db.refresh(memory)


@router.post(
    "/memories/capture",
    response_model=MemoryResponse,
    status_code=201,
    summary="Capture a new memory (legacy)",
    description="Legacy capture endpoint. Prefer /memories/capture/text, /voice, or /form.",
)
async def capture_memory(
    capture: MemoryCapture,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Legacy capture endpoint. Creates a memory record and queues refinement."""
    memory = await _create_memory(
        db=db,
        user=current_user,
        raw_input=capture.raw_input,
        input_type=capture.input_type,
    )
    return _memory_response(memory)


@router.post(
    "/memories/capture/text",
    response_model=MemoryResponse,
    status_code=201,
    summary="Capture a text memory",
    description="Capture a memory from raw text input.",
)
async def capture_text_memory(
    capture: MemoryTextCapture,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Capture a memory from raw text input.

    Args:
        capture: MemoryTextCapture schema with raw_input text.
        background_tasks: FastAPI background task queue.
        current_user: Current authenticated user.
        db: Database session.

    Returns:
        MemoryResponse with processing_state='raw'.
    """
    memory = await _create_memory(
        db=db,
        user=current_user,
        raw_input=capture.raw_input,
        input_type="text",
    )
    await _structure_and_update_memory(db, memory)
    background_tasks.add_task(_schedule_refinement, str(memory.id), str(memory.user_id))
    return _memory_response(memory)


@router.post(
    "/memories/capture/voice",
    response_model=MemoryResponse,
    status_code=201,
    summary="Capture a voice memory",
    description="Capture a memory from an audio file. Audio is transcribed to text before storage.",
)
async def capture_voice_memory(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="Audio file containing the voice memory"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Capture a memory from an audio file.

    Args:
        audio: Uploaded audio file.
        background_tasks: FastAPI background task queue.
        current_user: Current authenticated user.
        db: Database session.

    Returns:
        MemoryResponse with transcription as raw_input and processing_state='raw'.
    """
    audio_bytes = await audio.read()
    transcription = await _transcribe_audio(audio_bytes)

    memory = await _create_memory(
        db=db,
        user=current_user,
        raw_input=transcription,
        input_type="voice",
    )
    await _structure_and_update_memory(db, memory)
    background_tasks.add_task(_schedule_refinement, str(memory.id), str(memory.user_id))
    return _memory_response(memory)


@router.post(
    "/memories/capture/form",
    response_model=MemoryResponse,
    status_code=201,
    summary="Capture a form memory",
    description="Capture a memory from structured form input including mood, tags, people, and location.",
)
async def capture_form_memory(
    capture: MemoryFormCapture,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Capture a memory from structured form input.

    Args:
        capture: MemoryFormCapture schema with raw_input and optional structured fields.
        current_user: Current authenticated user.
        db: Database session.

    Returns:
        MemoryResponse with provided metadata and processing_state='raw'.
    """
    memory = await _create_memory(
        db=db,
        user=current_user,
        raw_input=capture.raw_input,
        input_type="form",
        mood=capture.mood,
        tags=capture.tags,
        importance_level=capture.importance_level,
    )

    await _structure_and_update_memory(
        db=db,
        memory=memory,
        override_mood=capture.mood,
        override_tags=capture.tags,
        override_importance=capture.importance_level,
        override_people=capture.people,
        override_location=capture.location,
    )
    background_tasks.add_task(_schedule_refinement, str(memory.id), str(memory.user_id))
    return _memory_response(memory)


def _matches_filters(memory: Memory, filters: SearchFilters | None) -> bool:
    """Return True if a memory passes the structured filters."""
    if filters is None:
        return True

    created = as_utc(memory.created_at)
    if filters.date_range_start and created < as_utc(filters.date_range_start):
        return False
    if filters.date_range_end and created > as_utc(filters.date_range_end):
        return False

    if filters.mood and memory.mood != filters.mood:
        return False

    if filters.importance_min is not None and memory.importance_level < filters.importance_min:
        return False
    if filters.importance_max is not None and memory.importance_level > filters.importance_max:
        return False

    if filters.tags:
        memory_tags = set(memory.tags or [])
        if not any(tag in memory_tags for tag in filters.tags):
            return False

    return True


def _memory_searchable_text(memory: Memory) -> str:
    """Return concatenated text from raw_input, title, and summary for full-text search."""
    parts = [memory.raw_input or ""]
    content = memory.structured_content or {}
    if isinstance(content, dict):
        parts.append(content.get("title", ""))
        parts.append(content.get("summary", ""))
    return " ".join(part for part in parts if part).lower()


def _full_text_score(memory: Memory, text_query: str) -> float:
    """Compute a simple full-text relevance score for SQLite/local dev.

    On PostgreSQL this should be replaced with ts_rank_cd over a tsvector column.
    """
    if not text_query or not text_query.strip():
        return 0.0

    searchable = _memory_searchable_text(memory)
    query_terms = [term.strip().lower() for term in text_query.split() if term.strip()]
    if not query_terms:
        return 0.0

    matches = sum(1 for term in query_terms if term in searchable)
    return matches / len(query_terms)


def _semantic_score(memory: Memory, query_embedding: list[float]) -> float:
    """Compute cosine similarity between memory embedding and query embedding."""
    if not query_embedding:
        return 0.0
    embedding = deserialize_embedding(memory.embedding)
    if not embedding or len(embedding) != len(query_embedding):
        return 0.0
    return cosine_similarity(query_embedding, embedding)


def _filter_bonus(memory: Memory, filters: SearchFilters | None) -> float:
    """Small bonus for memories that match structured filters (0 or 0.1)."""
    return 0.1 if _matches_filters(memory, filters) else 0.0


async def _search_memories(
    db: AsyncSession,
    user_id: str,
    query: SearchQuery,
    unlocked_ids: set[str] | None = None,
) -> SearchResponse:
    """Perform hybrid search: full-text + semantic + structured filters.

    Locked (private, not-unlocked) memories are excluded entirely: scoring them
    would leak whether their content matches the query.
    """
    from sqlalchemy import desc

    unlocked_ids = unlocked_ids or set()
    text_query = (query.text or "").strip()
    semantic_query = (query.semantic or "").strip()
    filters = query.filters

    # Generate query embedding for semantic search.
    query_embedding: list[float] = []
    if semantic_query:
        query_embedding = await generate_embedding(semantic_query)

    # Fetch candidate memories for this user.
    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(desc(Memory.created_at))
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    scored: list[tuple[float, Memory]] = []
    for memory in memories:
        if is_locked(memory, unlocked_ids):
            continue
        # Filter pre-check: skip memories that fail structured filters unless
        # they have some text/semantic signal, so pure filter mismatches drop out.
        passes_filter = _matches_filters(memory, filters)
        full_text = _full_text_score(memory, text_query) if text_query else 0.0
        semantic = _semantic_score(memory, query_embedding) if query_embedding else 0.0

        # If no text/semantic query, use filter match as the only signal.
        if not text_query and not query_embedding:
            if passes_filter:
                scored.append((0.5, memory))
            continue

        # Weighted combination: 0.3 full-text + 0.4 semantic + 0.3 filter bonus.
        combined = 0.3 * full_text + 0.4 * semantic + (0.3 * _filter_bonus(memory, filters))
        if combined > 0:
            scored.append((combined, memory))

    scored.sort(key=lambda item: item[0], reverse=True)

    total = len(scored)
    offset = query.offset
    limit = query.limit
    page = scored[offset : offset + limit]

    results = []
    for score, memory in page:
        content = memory.structured_content or {}
        title = content.get("title") if isinstance(content, dict) else None
        summary = content.get("summary") if isinstance(content, dict) else None
        event_date = content.get("event_date") if isinstance(content, dict) else None
        if not event_date:
            event_date = memory.event_date
        results.append(
            SearchResult(
                memory_id=memory.id,
                title=title,
                summary=summary,
                score=round(float(score), 4),
                event_date=event_date,
                created_at=memory.created_at,
            )
        )

    return SearchResponse(results=results, total=total, limit=limit, offset=offset)


@router.post(
    "/memories/search/semantic",
    response_model=SearchResponse,
    summary="Semantic memory search",
    description="Search memories by semantic similarity to a query string.",
)
async def search_memories_semantic(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> SearchResponse:
    """Return the top-k memories most semantically similar to the query.

    Uses in-memory cosine similarity for SQLite/local dev. On PostgreSQL with
    pgvector this should be replaced by a database-level similarity query.
    """
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    search_query = SearchQuery(semantic=query, limit=limit, offset=0)
    return await _search_memories(db, str(current_user.id), search_query, unlocked_ids)


@router.post(
    "/memories/search",
    response_model=SearchResponse,
    summary="Hybrid memory search",
    description="Search memories with full-text, semantic, and structured filters.",
)
async def search_memories(
    query: SearchQuery,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> SearchResponse:
    """Perform hybrid search across text, semantic, and filters."""
    return await _search_memories(db, str(current_user.id), query, unlocked_ids)


@router.post(
    "/memories/search/natural",
    response_model=SearchResponse,
    summary="Natural language memory search",
    description="Parse a natural language query and run hybrid search.",
)
async def search_memories_natural(
    query: str,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> SearchResponse:
    """Parse natural language into SearchQuery, then perform hybrid search."""
    search_query = await parse_search_query(query)
    # Override pagination params from URL if provided.
    search_query.limit = max(1, min(100, limit))
    search_query.offset = max(0, offset)
    return await _search_memories(db, str(current_user.id), search_query, unlocked_ids)


@router.get(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Get a memory by ID",
    description="Retrieve a single memory with all details. Returns 404 if not found or not owned by the user.",
)
async def get_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> MemoryResponse:
    """Retrieve a single memory by ID, scoped to the current user."""
    stmt = select(Memory).where(Memory.id == str(memory_id)).where(Memory.user_id == current_user.id)
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()

    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )

    return _memory_response(memory, unlocked_ids)


@router.get(
    "/memories",
    response_model=list[MemoryResponse],
    summary="List user memories",
    description="List the current user's memories with pagination and sorting.",
)
async def list_memories(
    limit: int = 20,
    offset: int = 0,
    sort: str = "created_at_desc",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[MemoryResponse]:
    """List memories for the current user with pagination.

    Args:
        limit: Maximum number of memories to return (1-100).
        offset: Number of memories to skip.
        sort: Sort order. Supports created_at_desc (default) and created_at_asc.
    """
    from sqlalchemy import desc, asc

    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    order = [desc(Memory.created_at), desc(Memory.id)]
    if sort == "created_at_asc":
        order = [asc(Memory.created_at), asc(Memory.id)]

    stmt = (
        select(Memory)
        .where(Memory.user_id == current_user.id)
        .order_by(*order)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    return [_memory_response(memory, unlocked_ids) for memory in memories]


@router.patch(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Update a memory",
    description="Apply partial updates to a memory. Only provided fields are changed.",
)
async def update_memory(
    memory_id: UUID,
    update: MemoryUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> MemoryResponse:
    """Apply partial updates to a memory owned by the current user.

    Editing the raw text invalidates everything the agents derived from it, so
    the memory is requeued for refinement + enrichment. Any other field set in
    the same request is treated as a user override and re-applied after the
    agents run, so a manual correction is never clobbered.
    """
    stmt = select(Memory).where(Memory.id == str(memory_id)).where(Memory.user_id == current_user.id)
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()

    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )

    if update.is_private is not None:
        memory.is_private = update.is_private

    # Detect a genuine text change before overwriting it.
    raw_input_changed = (
        update.raw_input is not None and update.raw_input != memory.raw_input
    )

    if update.raw_input is not None:
        memory.raw_input = update.raw_input

    if update.structured_content is not None:
        memory.structured_content = update.structured_content.model_dump(mode="json")

    if update.tags is not None:
        memory.tags = [tag.lower()[:50] for tag in update.tags if tag]

    if update.mood is not None:
        memory.mood = update.mood[:50] if update.mood else None

    if update.importance_level is not None:
        memory.importance_level = update.importance_level

    if update.related_memory_ids is not None:
        memory.related_memory_ids = [str(m_id) for m_id in update.related_memory_ids]

    # Distinguish "field omitted" from "field explicitly cleared". Without this,
    # clearing a fuzzy label in the UI (sending null) would be ignored.
    provided = update.model_fields_set

    if "event_date" in provided:
        if update.event_date is not None:
            memory.event_date = update.event_date
            # An explicit date supersedes a fuzzy period; otherwise the label
            # would keep overriding the displayed date.
            memory.date_precision = "exact"
            memory.event_date_end = None
            memory.date_label = None
        else:
            # Explicitly cleared.
            memory.event_date = None

    if update.date_precision is not None:
        memory.date_precision = update.date_precision

    if "event_date_end" in provided:
        memory.event_date_end = update.event_date_end

    if "date_label" in provided:
        memory.date_label = update.date_label[:120] if update.date_label else None

    # Copy rather than mutate in place: structured_content is a JSON column and
    # reassigning the identical dict object does not mark the attribute dirty,
    # so the UPDATE would be skipped.
    content = dict(memory.structured_content) if isinstance(memory.structured_content, dict) else {}

    if update.title is not None:
        content["title"] = update.title[:255] if update.title else None

    if update.summary is not None:
        content["summary"] = update.summary

    if update.people is not None:
        content["people"] = [str(p) for p in update.people if p]

    if update.location is not None:
        content["location"] = update.location[:100] if update.location else None

    # Refresh denormalized fields from structured_content, but never let the
    # stored (agent-derived) values clobber an explicit user edit above. Date
    # fields are only re-read when the user did not touch any of them.
    if isinstance(content, dict):
        if update.mood is None and content.get("mood"):
            memory.mood = content["mood"]
        if update.importance_level is None and content.get("importance_level") is not None:
            memory.importance_level = content["importance_level"]
        if update.tags is None and content.get("initial_tags"):
            memory.tags = [tag.lower()[:50] for tag in content["initial_tags"] if tag]

        user_touched_date = bool(
            provided & {"event_date", "date_label", "date_precision", "event_date_end"}
        )
        if not user_touched_date and content.get("event_date"):
            parsed = content["event_date"]
            if isinstance(parsed, str):
                try:
                    parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
                except ValueError:
                    parsed = None
            if parsed is not None:
                memory.event_date = parsed
        if not user_touched_date:
            if content.get("date_precision"):
                memory.date_precision = content["date_precision"]
            if content.get("date_label"):
                memory.date_label = content["date_label"]

    memory.structured_content = content
    _apply_review_flags(memory)

    # If the source text changed, re-run the agents. Fields the user set in
    # this request are passed as overrides so they survive the rerun.
    if raw_input_changed:
        overrides = {
            key: value
            for key, value in {
                "title": update.title,
                "summary": update.summary,
                "tags": update.tags,
                "mood": update.mood,
                "importance_level": update.importance_level,
                "event_date": (
                    update.event_date.isoformat() if update.event_date else None
                ),
                "date_precision": update.date_precision,
                "date_label": update.date_label,
                "event_date_end": (
                    update.event_date_end.isoformat() if update.event_date_end else None
                ),
                "people": update.people,
                "location": update.location,
            }.items()
            if value is not None
        }
        memory.processing_state = "capturing"

    await db.commit()
    await db.refresh(memory)

    if raw_input_changed:
        background_tasks.add_task(
            _schedule_refinement,
            str(memory.id),
            str(memory.user_id),
            overrides,
        )

    return _memory_response(memory, unlocked_ids)


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a memory",
    description="Hard delete a memory and its associated entities. Returns 404 if not found or not owned.",
)
async def delete_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a memory owned by the current user."""
    stmt = select(Memory).where(Memory.id == str(memory_id)).where(Memory.user_id == current_user.id)
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()

    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )

    # Capture the entities this memory mentions before deletion, so their
    # cached mention counts can be corrected afterwards. Deleting the memory
    # cascades the mention rows, which would otherwise leave counts inflated.
    affected_entity_ids = await entity_ids_for_memory(db, str(memory.id))

    await db.delete(memory)
    await db.commit()

    if affected_entity_ids:
        await recompute_entity_stats(db, affected_entity_ids)
        await db.commit()

