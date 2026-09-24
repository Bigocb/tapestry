"""Review queue routes.

Memories the pipeline could not confidently finalize (currently: no event date
could be found) are flagged `needs_review` and surfaced here so the user can
correct them. This is intentionally a general mechanism: more reasons can be
added later without changing the API shape.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db import get_db, Memory, User
from app.dependencies import get_current_user
from app.models.schemas import ReviewQueueResponse
from app.privacy import get_unlocked_memory_ids
from app.routes.memories import _memory_response

router = APIRouter()


@router.get(
    "/review",
    response_model=ReviewQueueResponse,
    summary="List memories needing review",
    description=(
        "Return memories flagged for review, most recent first, with the total "
        "count. Optionally filter by review_reason."
    ),
)
async def get_review_queue(
    reason: Optional[str] = Query(None, description="Filter by review_reason"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> ReviewQueueResponse:
    """Return the current user's review queue."""
    filters = [
        Memory.user_id == current_user.id,
        Memory.needs_review.is_(True),
    ]
    if reason:
        filters.append(Memory.review_reason == reason)

    count_result = await db.execute(select(func.count()).select_from(Memory).where(*filters))
    total = int(count_result.scalar_one())

    stmt = (
        select(Memory)
        .where(*filters)
        .order_by(Memory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    return ReviewQueueResponse(
        items=[_memory_response(memory, unlocked_ids) for memory in memories],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/review/count",
    summary="Count memories needing review",
    description="Lightweight endpoint for nav badges.",
)
async def get_review_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the number of memories awaiting review."""
    result = await db.execute(
        select(func.count())
        .select_from(Memory)
        .where(Memory.user_id == current_user.id, Memory.needs_review.is_(True))
    )
    return {"count": int(result.scalar_one())}
