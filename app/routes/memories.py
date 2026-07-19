"""Memory capture and retrieval routes.

Routes for capturing, retrieving, updating, and deleting memories.
Includes support for voice, text, and form inputs.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
from uuid import UUID
import uuid

from app.db import get_db, Memory, User
from app.db.connection import engine
from app.models.schemas import MemoryCapture, MemoryResponse, MemoryTextCapture, MemoryFormCapture
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


async def _schedule_refinement(memory_id: str) -> None:
    """Background task: run the refinement step for a captured memory.

    This is a stub for Issue 6 (Refinement Agent). For now it marks the memory
    as 'refined' so the async pipeline path is wired end-to-end.
    """
    session_factory = get_background_session_factory()
    async with session_factory() as db:
        stmt = select(Memory).where(Memory.id == memory_id)
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            return

        memory.processing_state = "refined"
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

    # Store additional structured fields in the memory record. Form fields like
    # people and location are kept inside structured_content for now.
    memory.structured_content = {
        "people": capture.people,
        "location": capture.location,
        "importance_level": capture.importance_level,
    }
    await db.commit()
    await db.refresh(memory)

    background_tasks.add_task(_schedule_refinement, str(memory.id))
    return _memory_response(memory)
