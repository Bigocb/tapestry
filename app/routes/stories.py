"""Story generation and retrieval routes."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.db import get_db, Memory, Story, User
from app.models.schemas import StoryGenerate, StoryResponse, StoryExport
from app.agents import llm
from app.agents.story import generate_story
from app.dependencies import get_current_user

router = APIRouter()


def _memory_to_story_context(memory: Memory) -> dict:
    """Convert a Memory ORM object into a dict suitable for the Story Agent."""
    content = memory.structured_content or {}
    if not isinstance(content, dict):
        content = {}
    return {
        "title": content.get("title", "Untitled"),
        "summary": content.get("summary", memory.raw_input),
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "mood": memory.mood,
        "tags": memory.tags,
        "importance_level": memory.importance_level,
    }


def _story_response(story: Story) -> StoryResponse:
    return StoryResponse(
        id=story.id,
        user_id=story.user_id,
        title=story.title,
        narrative=story.narrative,
        memory_ids=[UUID(m_id) for m_id in story.memory_ids],
        story_type=story.story_type,
        created_at=story.created_at,
        updated_at=story.updated_at,
    )


async def _validate_memory_ownership(
    db: AsyncSession,
    memory_ids: list[UUID],
    user_id: str,
) -> list[Memory]:
    """Verify all memory IDs belong to the user and return the memories."""
    if not memory_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one memory ID is required",
        )

    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id)
        .where(Memory.id.in_([str(m_id) for m_id in memory_ids]))
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    found_ids = {str(memory.id) for memory in memories}
    requested_ids = {str(m_id) for m_id in memory_ids}
    missing = requested_ids - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory IDs not found for user: {sorted(missing)}",
        )

    # Preserve requested order.
    order_map = {str(m_id): index for index, m_id in enumerate(memory_ids)}
    return sorted(memories, key=lambda m: order_map[str(m.id)])


@router.post(
    "/stories/generate",
    response_model=StoryResponse,
    status_code=201,
    summary="Generate a story",
    description="Generate a markdown narrative from selected memories and store it.",
)
async def generate_story_endpoint(
    request: StoryGenerate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Generate a story from selected memories."""
    memories = await _validate_memory_ownership(
        db=db,
        memory_ids=request.memory_ids,
        user_id=str(current_user.id),
    )

    memory_contexts = [_memory_to_story_context(memory) for memory in memories]
    async with llm.using(db, str(current_user.id), "story"):
        narrative = await generate_story(
            story_type=request.story_type,
            memories=memory_contexts,
            custom_prompt=request.custom_prompt,
        )

    # Derive a title from the first heading of the narrative if present.
    title = request.story_type.replace("_", " ").title()
    for line in narrative.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    story = Story(
        user_id=current_user.id,
        title=title,
        narrative=narrative,
        memory_ids=[str(m_id) for m_id in request.memory_ids],
        story_type=request.story_type,
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)

    return _story_response(story)


@router.get(
    "/stories/{story_id}",
    response_model=StoryResponse,
    summary="Get a story by ID",
    description="Retrieve a single story with its narrative.",
)
async def get_story(
    story_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Retrieve a story by ID, scoped to the current user."""
    stmt = select(Story).where(Story.id == str(story_id)).where(Story.user_id == current_user.id)
    result = await db.execute(stmt)
    story = result.scalar_one_or_none()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found",
        )

    return _story_response(story)


@router.get(
    "/stories",
    response_model=list[StoryResponse],
    summary="List user stories",
    description="List the current user's stories with pagination.",
)
async def list_stories(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StoryResponse]:
    """List stories for the current user with pagination."""
    from sqlalchemy import desc

    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    stmt = (
        select(Story)
        .where(Story.user_id == current_user.id)
        .order_by(desc(Story.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    stories = result.scalars().all()

    return [_story_response(story) for story in stories]


@router.post(
    "/stories/{story_id}/export",
    summary="Export a story",
    description="Export a story to markdown, plain text, or JSON format.",
)
async def export_story(
    story_id: UUID,
    export: StoryExport,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export a story in the requested format."""
    stmt = select(Story).where(Story.id == str(story_id)).where(Story.user_id == current_user.id)
    result = await db.execute(stmt)
    story = result.scalar_one_or_none()

    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Story not found",
        )

    fmt = export.format
    if fmt == "markdown":
        return {"format": "markdown", "content": story.narrative}
    elif fmt == "txt":
        # Simple plain text: strip markdown heading markers.
        text = story.narrative.replace("# ", "").replace("## ", "")
        return {"format": "txt", "content": text}
    elif fmt == "json":
        return {
            "format": "json",
            "content": {
                "id": str(story.id),
                "title": story.title,
                "narrative": story.narrative,
                "memory_ids": story.memory_ids,
                "story_type": story.story_type,
                "created_at": story.created_at.isoformat() if story.created_at else None,
            },
        }

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported export format",
    )
