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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
from uuid import UUID
import uuid

from app.db import get_db, Memory, User
from app.db.connection import engine
from app.agents.capture import structure_memory
from app.agents.embeddings import (
    cosine_similarity,
    deserialize_embedding,
    generate_embedding,
    serialize_embedding,
)
from app.agents.enrichment import enrich_memory
from app.agents.refinement import refine_memory
from app.agents.search import parse_search_query
from app.models.schemas import (
    MemoryCapture,
    MemoryResponse,
    MemoryTextCapture,
    MemoryFormCapture,
    SearchFilters,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from app.dependencies import get_current_user

router = APIRouter()

# Background task session factory for work that outlives the request.
# Tests can override this with a factory bound to the test database.
BackgroundSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def get_background_session_factory() -> async_sessionmaker:
    """Return the current background task session factory.

    Override point for tests so background tasks share the test database.
    """
    return BackgroundSessionLocal


async def _fetch_recent_memories(
    db: AsyncSession, user_id: str, exclude_memory_id: str, limit: int = 5
) -> list[dict]:
    """Fetch the user's most recent memories (excluding the given one) as context."""
    from sqlalchemy import desc

    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id)
        .where(Memory.id != exclude_memory_id)
        .order_by(desc(Memory.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    context = []
    for mem in memories:
        content = mem.structured_content or {}
        context.append(
            {
                "title": content.get("title", "Untitled")
                if isinstance(content, dict)
                else "Untitled",
                "summary": content.get("summary", "")
                if isinstance(content, dict)
                else "",
                "entities": content.get("entities", [])
                if isinstance(content, dict)
                else [],
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
            }
        )
    return context


async def _generate_embedding_for_memory(memory: Memory) -> None:
    """Generate and attach an embedding from the memory's searchable text.

    Uses the memory title + summary when available, otherwise raw_input.
    """
    content = memory.structured_content or {}
    if isinstance(content, dict):
        searchable_parts = [
            content.get("title", ""),
            content.get("summary", ""),
            memory.raw_input,
        ]
    else:
        searchable_parts = [memory.raw_input]

    searchable_text = " ".join(part for part in searchable_parts if part).strip()
    embedding = await generate_embedding(searchable_text)
    memory.embedding = serialize_embedding(embedding) if embedding else None


async def _find_similar_memories(
    db: AsyncSession,
    memory: Memory,
    exclude_memory_id: str,
    limit: int = 5,
) -> list[dict]:
    """Find the top-k memories most similar to the given memory by embedding."""
    from sqlalchemy import desc

    target_embedding = deserialize_embedding(memory.embedding)
    if not target_embedding:
        return []

    stmt = (
        select(Memory)
        .where(Memory.user_id == memory.user_id)
        .where(Memory.id != exclude_memory_id)
        .where(Memory.embedding.is_not(None))
        .order_by(desc(Memory.created_at))
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    scored = []
    for mem in memories:
        embedding = deserialize_embedding(mem.embedding)
        if not embedding or len(embedding) != len(target_embedding):
            continue
        score = cosine_similarity(target_embedding, embedding)
        scored.append((score, mem))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:limit]

    similar = []
    for score, mem in top:
        content = mem.structured_content or {}
        similar.append(
            {
                "memory_id": str(mem.id),
                "title": content.get("title") if isinstance(content, dict) else None,
                "summary": content.get("summary")
                if isinstance(content, dict)
                else None,
                "score": round(float(score), 4),
            }
        )
    return similar


async def _run_refinement(memory: Memory, db: AsyncSession) -> None:
    """Run the Refinement Agent on a memory."""
    recent_memories = await _fetch_recent_memories(
        db=db,
        user_id=str(memory.user_id),
        exclude_memory_id=str(memory.id),
    )
    refined = await refine_memory(
        raw_input=memory.raw_input,
        structured_content=memory.structured_content or {},
        recent_memories=recent_memories,
    )

    memory.structured_content = refined.model_dump()
    memory.mood = refined.mood
    memory.importance_level = refined.importance_level
    memory.tags = refined.initial_tags


async def _run_enrichment(memory: Memory, db: AsyncSession) -> None:
    """Run the Enrichment Agent on a memory using similar memories as context."""
    await _generate_embedding_for_memory(memory)

    similar_memories = await _find_similar_memories(
        db=db,
        memory=memory,
        exclude_memory_id=str(memory.id),
        limit=5,
    )

    enriched, related_ids = await enrich_memory(
        memory=memory.structured_content or {},
        similar_memories=similar_memories,
    )

    memory.structured_content = enriched.model_dump()
    memory.mood = enriched.mood
    memory.importance_level = enriched.importance_level
    memory.tags = enriched.initial_tags
    memory.related_memory_ids = related_ids


async def _schedule_refinement(memory_id: str) -> None:
    """Background task: run Refinement, Enrichment, and embedding generation.

    This task now covers the full agent pipeline for a captured memory.
    On failure, marks the state as 'refined_failed' so the issue is observable.
    """
    session_factory = get_background_session_factory()
    async with session_factory() as db:
        stmt = select(Memory).where(Memory.id == memory_id)
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            return

        try:
            await _run_refinement(memory, db)
            memory.processing_state = "refined"
            await db.commit()

            await _run_enrichment(memory, db)
            memory.processing_state = "enriched"
            await db.commit()
        except Exception:
            memory.processing_state = "refined_failed"
            await db.commit()


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


def _memory_response(memory: Memory) -> MemoryResponse:
    """Convert a Memory ORM object to a MemoryResponse Pydantic model."""
    return MemoryResponse(
        id=memory.id,
        user_id=memory.user_id,
        raw_input=memory.raw_input,
        input_type=memory.input_type,
        structured_content=memory.structured_content,
        tags=memory.tags,
        mood=memory.mood,
        importance_level=memory.importance_level,
        processing_state=memory.processing_state,
        related_memory_ids=memory.related_memory_ids,
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
        id=str(uuid.uuid4()),
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

    memory.structured_content = structured.model_dump()

    # Update denormalized top-level fields for querying/filtering.
    memory.mood = structured.mood
    memory.importance_level = structured.importance_level
    memory.tags = structured.initial_tags

    # Merge form-only fields (people, location) into structured_content.
    existing = memory.structured_content or {}
    if override_people:
        existing["people"] = override_people
    if override_location:
        existing["location"] = override_location
    memory.structured_content = existing

    memory.processing_state = "capturing"
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
    background_tasks.add_task(_schedule_refinement, str(memory.id))
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
    background_tasks.add_task(_schedule_refinement, str(memory.id))
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
    background_tasks.add_task(_schedule_refinement, str(memory.id))
    return _memory_response(memory)


def _matches_filters(memory: Memory, filters: SearchFilters | None) -> bool:
    """Return True if a memory passes the structured filters."""
    if filters is None:
        return True

    if filters.date_range_start and memory.created_at < filters.date_range_start:
        return False
    if filters.date_range_end and memory.created_at > filters.date_range_end:
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
) -> SearchResponse:
    """Perform hybrid search: full-text + semantic + structured filters."""
    from sqlalchemy import desc

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
        results.append(
            SearchResult(
                memory_id=memory.id,
                title=title,
                summary=summary,
                score=round(float(score), 4),
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
    return await _search_memories(db, str(current_user.id), search_query)


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
) -> SearchResponse:
    """Perform hybrid search across text, semantic, and filters."""
    return await _search_memories(db, str(current_user.id), query)


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
) -> SearchResponse:
    """Parse natural language into SearchQuery, then perform hybrid search."""
    search_query = await parse_search_query(query)
    # Override pagination params from URL if provided.
    search_query.limit = max(1, min(100, limit))
    search_query.offset = max(0, offset)
    return await _search_memories(db, str(current_user.id), search_query)


