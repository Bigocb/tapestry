"""Timeline route (Issue 17).

GET /api/timeline returns the current user's memories ordered chronologically
by event date (falling back to creation date), with date range, tag, and mood
filters plus pagination.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import Optional

from app.db import get_db, Memory, User, as_utc
from app.dependencies import get_current_user
from app.models.schemas import MemoryResponse
from app.privacy import get_unlocked_memory_ids
from app.routes.memories import _memory_response

router = APIRouter()


def _timeline_date(memory: Memory) -> Optional[datetime]:
    """Return the (UTC-aware) date used to place a memory on the timeline.

    None means the memory has a fuzzy label but no anchor date (e.g. "Sometime
    in middle school"); it still belongs on the timeline, just not at a fixed
    chronological point.
    """
    return as_utc(memory.event_date)


def _has_time_placement(memory: Memory) -> bool:
    """True if the memory carries any time information at all.

    A fuzzy period (decade, range, named life period) is a real answer, so such
    a memory is placed on the timeline rather than hidden.
    """
    return (
        memory.event_date is not None
        or memory.date_precision in ("decade", "range")
        or bool(memory.date_label)
    )


def _matches_timeline_filters(
    memory: Memory,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    tags: Optional[list[str]],
    mood: Optional[str],
) -> bool:
    """Return True if a memory passes the timeline filters."""
    # Memories with no time information live in the review queue instead.
    if not _has_time_placement(memory):
        return False

    memory_date = _timeline_date(memory)

    # Date-range filters only make sense for anchored dates; label-only
    # memories cannot be compared and are excluded when a range is given.
    if start_date or end_date:
        if memory_date is None:
            return False
        if start_date and memory_date < as_utc(start_date):
            return False
        if end_date and memory_date > as_utc(end_date):
            return False

    if mood and memory.mood != mood:
        return False

    if tags:
        memory_tags = set(memory.tags or [])
        if not any(tag in memory_tags for tag in tags):
            return False

    return True


@router.get(
    "/timeline",
    response_model=list[MemoryResponse],
    summary="Get memory timeline",
    description=(
        "Return the current user's memories ordered chronologically by event "
        "date (falling back to creation date). Supports date range, tag, and "
        "mood filters plus pagination."
    ),
)
async def get_timeline(
    start_date: Optional[datetime] = Query(None, description="Inclusive lower bound"),
    end_date: Optional[datetime] = Query(None, description="Inclusive upper bound"),
    tags: Optional[list[str]] = Query(None, description="Filter by ANY of these tags"),
    mood: Optional[str] = Query(None, description="Filter by mood"),
    limit: int = Query(50, ge=1, le=200, description="Max memories to return"),
    offset: int = Query(0, ge=0, description="Number of memories to skip"),
    order: str = Query("desc", description="'desc' (newest first) or 'asc'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[MemoryResponse]:
    """Return the user's memories in chronological order."""
    stmt = select(Memory).where(Memory.user_id == current_user.id)
    result = await db.execute(stmt)
    memories = result.scalars().all()

    filtered = [
        memory
        for memory in memories
        if _matches_timeline_filters(memory, start_date, end_date, tags, mood)
    ]

    descending = order != "asc"

    # Label-only memories have no anchor date; fall back to creation time so the
    # comparison never sees None (which would raise) and the order stays stable.
    def _sort_key(memory: Memory):
        anchor = _timeline_date(memory)
        if anchor is None:
            anchor = as_utc(memory.created_at)
        return (anchor, str(memory.id))

    filtered.sort(key=_sort_key, reverse=descending)

    page = filtered[offset : offset + limit]
    return [_memory_response(memory, unlocked_ids) for memory in page]
