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
from app.agents.refinement import refine_memory
from app.models.schemas import (
    MemoryCapture,
    MemoryResponse,
    MemoryTextCapture,
    MemoryFormCapture,
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


async def _schedule_refinement(memory_id: str) -> None:
    """Background task: run Refinement + embedding generation for a memory.

    Loads the memory, fetches recent context memories, calls the Refinement Agent,
    generates an embedding, and stores the updated StructuredMemory. On failure,
    marks the state as 'refined_failed' so the issue is observable.
    """
    session_factory = get_background_session_factory()
    async with session_factory() as db:
        stmt = select(Memory).where(Memory.id == memory_id)
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            return

        try:
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
            await _generate_embedding_for_memory(memory)
            memory.processing_state = "refined"
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
    from sqlalchemy import desc

    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    query_embedding = await generate_embedding(query)
    if not query_embedding:
        return SearchResponse(results=[], total=0, limit=limit, offset=0)

    # Fetch user's memories with embeddings.
    stmt = (
        select(Memory)
        .where(Memory.user_id == current_user.id)
        .where(Memory.embedding.is_not(None))
        .order_by(desc(Memory.created_at))
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    scored = []
    for memory in memories:
        embedding = deserialize_embedding(memory.embedding)
        if not embedding or len(embedding) != len(query_embedding):
            continue
        score = cosine_similarity(query_embedding, embedding)
        scored.append((score, memory))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:limit]

    results = []
    for score, memory in top:
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

    return SearchResponse(results=results, total=len(results), limit=limit, offset=0)
