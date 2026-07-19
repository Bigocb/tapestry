"""Memory capture and retrieval routes.

Routes for capturing, retrieving, updating, and deleting memories.
Includes support for voice, text, and form inputs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import uuid

from app.db import get_db, Memory, User
from app.models.schemas import MemoryCapture, MemoryResponse
from app.dependencies import get_current_user

router = APIRouter()


@router.post(
    "/memories/capture",
    response_model=MemoryResponse,
    status_code=201,
    summary="Capture a new memory",
    description="Capture a memory from voice, text, or form input. Sets initial processing_state to 'raw'.",
)
async def capture_memory(
    capture: MemoryCapture,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """Capture a new memory from user input.

    Accepts raw_input (text, transcribed voice, or form data) and input_type.
    Creates Memory record with processing_state='raw' and queues for refinement.

    Args:
        capture: MemoryCapture schema with raw_input and input_type
        current_user: Current authenticated user
        db: Database session

    Returns:
        MemoryResponse: Newly created memory with ID, timestamps, etc.

    Raises:
        401: If user is not authenticated
        422: If validation fails (bad input_type, empty raw_input, etc.)
    """
    # Create new memory record
    memory = Memory(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        raw_input=capture.raw_input,
        input_type=capture.input_type,
        processing_state="raw",
        tags=[],
        related_memory_ids=[],
    )

    db.add(memory)
    await db.commit()
    await db.refresh(memory)

    # Convert to response schema
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
