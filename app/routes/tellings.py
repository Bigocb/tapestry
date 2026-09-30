"""Tellings: one recounting becomes many memories.

A telling is submitted, split into proposed segments for review, and turned
into real memories only when the user commits. The segments live in their own
table rather than in ``memories`` behind a draft flag, so an unreviewed split
can never surface in the timeline, search, review queue or entity graph.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.telling import segment_transcript
from app.db import get_db, Memory, Telling, TellingSegment, User
from app.db.entities import sync_memory_entities
from app.db.memory_writes import apply_memory_date_fields, apply_review_flags
from app.dependencies import get_current_user
from app.models.schemas import (
    TellingCreate,
    TellingResponse,
    TellingSegmentResponse,
    TellingSegmentUpdate,
)

router = APIRouter()

PROPOSED = "proposed"
ACCEPTED = "accepted"
REJECTED = "rejected"
SEGMENT_STATUSES = {PROPOSED, ACCEPTED, REJECTED}

DRAFT = "draft"
COMMITTED = "committed"


def _segment_response(segment: TellingSegment) -> TellingSegmentResponse:
    """Flatten a segment's structured content for the review screen."""
    content = segment.structured_content or {}
    return TellingSegmentResponse(
        id=segment.id,
        ordinal=segment.ordinal,
        text=segment.text,
        status=segment.status,
        title=content.get("title"),
        summary=content.get("summary"),
        structured_content=content,
        event_date=segment.event_date,
        date_precision=segment.date_precision,
        event_date_end=segment.event_date_end,
        date_label=segment.date_label,
        memory_id=segment.memory_id,
    )


def _telling_response(telling: Telling) -> TellingResponse:
    return TellingResponse(
        id=telling.id,
        raw_transcript=telling.raw_transcript,
        input_type=telling.input_type,
        status=telling.status,
        error=telling.error,
        frame_date=telling.frame_date,
        frame_label=telling.frame_label,
        created_at=telling.created_at,
        segments=[_segment_response(segment) for segment in telling.segments],
    )


async def _load_telling(db: AsyncSession, user_id, telling_id) -> Telling:
    """Load one telling and its segments, scoped to its owner."""
    result = await db.execute(
        select(Telling)
        .where(Telling.id == telling_id, Telling.user_id == user_id)
        .options(selectinload(Telling.segments))
    )
    telling = result.scalar_one_or_none()
    if telling is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Telling not found"
        )
    return telling


@router.post(
    "/tellings",
    response_model=TellingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tell a story",
    description="Submit a recounting and get back a proposed split to review.",
)
async def capture_telling(
    payload: TellingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Store the transcript and propose a split for review."""
    telling = Telling(
        user_id=current_user.id,
        raw_transcript=payload.raw_transcript,
        input_type="text",
        status=DRAFT,
    )
    db.add(telling)
    await db.flush()

    # Split once, on the way in. Commit must not re-run this: the reviewed
    # content on each segment is authoritative.
    proposed = await segment_transcript(payload.raw_transcript)

    for ordinal, segment in enumerate(proposed):
        structured = segment.structured
        db.add(
            TellingSegment(
                telling_id=telling.id,
                user_id=current_user.id,
                ordinal=ordinal,
                text=segment.text,
                structured_content=structured.model_dump(mode="json"),
                event_date=structured.event_date,
                date_precision=structured.date_precision,
                event_date_end=structured.event_date_end,
                date_label=structured.date_label,
                status=PROPOSED,
            )
        )
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling.id))


@router.get(
    "/tellings/{telling_id}",
    response_model=TellingResponse,
    summary="Get a telling",
    description="Fetch a telling together with its proposed segments.",
)
async def get_telling(
    telling_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Fetch one telling and its proposed split."""
    telling = await _load_telling(db, current_user.id, telling_id)
    return _telling_response(telling)


async def commit_telling(db: AsyncSession, user_id, telling_id: UUID) -> Telling:
    """Turn a telling's accepted segments into real memories.

    The reviewed content on each segment is authoritative: the Capture Agent is
    deliberately *not* re-run here, because re-structuring one segment in
    isolation would throw away the narrative context segmentation recovered.

    Entities and review flags go through the same helpers a normal capture
    uses, so a committed memory is indistinguishable from a captured one.
    """
    telling = await _load_telling(db, user_id, telling_id)
    if telling.status == COMMITTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telling has already been committed",
        )

    for segment in telling.segments:
        # Only an explicit rejection excludes a segment; a proposal is the
        # default and commits.
        if segment.status == REJECTED:
            continue

        content = segment.structured_content or {}
        memory = Memory(
            user_id=user_id,
            raw_input=segment.text,
            input_type=telling.input_type,
            structured_content=segment.structured_content,
            mood=content.get("mood"),
            importance_level=content.get("importance_level", 5),
            tags=content.get("initial_tags", []),
            related_memory_ids=[],
            processing_state="capturing",
        )
        # The segment mirrors the memory's date columns, so the same helper
        # applies the resolved (and possibly fuzzy) date.
        apply_memory_date_fields(memory, segment)
        apply_review_flags(memory)

        db.add(memory)
        await db.flush()

        await sync_memory_entities(
            db, str(user_id), str(memory.id), memory.structured_content
        )
        segment.memory_id = memory.id

    telling.status = COMMITTED
    await db.commit()

    return telling


@router.patch(
    "/tellings/{telling_id}/segments/{segment_id}",
    response_model=TellingSegmentResponse,
    summary="Edit a proposed segment",
    description="Edit a segment's text, title or summary, or accept/reject it.",
)
async def update_segment(
    telling_id: UUID,
    segment_id: UUID,
    payload: TellingSegmentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingSegmentResponse:
    """Apply a reviewed edit to one proposed segment."""
    if payload.status is not None and payload.status not in SEGMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(SEGMENT_STATUSES)}",
        )

    telling = await _load_telling(db, current_user.id, telling_id)
    segment = next((item for item in telling.segments if item.id == segment_id), None)
    if segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
        )

    if payload.text is not None:
        segment.text = payload.text
    if payload.status is not None:
        segment.status = payload.status

    # Reassign rather than mutate: in-place JSON changes are not detected.
    content = dict(segment.structured_content or {})
    if payload.title is not None:
        content["title"] = payload.title
    if payload.summary is not None:
        content["summary"] = payload.summary
    segment.structured_content = content

    await db.commit()

    return _segment_response(segment)


@router.post(
    "/tellings/{telling_id}/commit",
    response_model=TellingResponse,
    summary="Commit a telling",
    description="Turn the telling's accepted segments into memories.",
)
async def commit_telling_endpoint(
    telling_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Create memories from the reviewed split."""
    await commit_telling(db, current_user.id, telling_id)
    return _telling_response(await _load_telling(db, current_user.id, telling_id))
