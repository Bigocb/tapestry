"""Tellings: one recounting becomes many memories.

A telling is submitted, split into proposed segments for review, and turned
into real memories only when the user commits. The segments live in their own
table rather than in ``memories`` behind a draft flag, so an unreviewed split
can never surface in the timeline, search, review queue or entity graph.
"""

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.telling import SegmentationResult, segment_transcript
from app.db import get_db, Memory, Telling, TellingSegment, User
from app.db.entities import sync_memory_entities
from app.db.memory_writes import apply_memory_date_fields, apply_review_flags
from app.dependencies import get_current_user
from app.privacy import get_unlocked_memory_ids
from app.routes.memories import _memory_response, _transcribe_audio
from app.models.schemas import (
    MemoryResponse,
    TellingCreate,
    TellingResponse,
    TellingSegmentMerge,
    TellingSegmentReorder,
    TellingSegmentResponse,
    TellingSegmentSplit,
    TellingSegmentUpdate,
    TellingTranscriptUpdate,
)

router = APIRouter()

PROPOSED = "proposed"
ACCEPTED = "accepted"
REJECTED = "rejected"
SEGMENT_STATUSES = {PROPOSED, ACCEPTED, REJECTED}

# Mirrors ResolvedDate.precision. A fuzzy period is a real answer, so these are
# all legitimate values for a user to set by hand.
DATE_PRECISIONS = {"exact", "month", "year", "decade", "range", "unknown"}

DRAFT = "draft"
COMMITTED = "committed"
TRANSCRIBING = "transcribing"
SEGMENTING = "segmenting"
FAILED = "failed"


def _background_session_factory():
    """Session factory for work that runs after the response has gone out.

    Read through the scheduler module so tests can point it at their database,
    exactly as the memory pipeline does.
    """
    from app.jobs import scheduler as scheduler_module

    return scheduler_module.BackgroundSessionLocal


async def _process_voice_telling(
    telling_id: str, user_id: str, audio_bytes: bytes
) -> None:
    """Transcribe a recording, split it, and record the outcome on the telling.

    Runs after the response, because transcribing a long recording takes
    minutes and the request cannot wait for it.
    """
    session_factory = _background_session_factory()

    async with session_factory() as db:
        telling = (
            await db.execute(select(Telling).where(Telling.id == telling_id))
        ).scalar_one_or_none()
        if telling is None:
            return

        try:
            telling.raw_transcript = await _transcribe_audio(audio_bytes)
            telling.status = SEGMENTING
            await db.flush()

            proposed = await segment_transcript(telling.raw_transcript)
            _store_segments(db, telling, user_id, proposed)
            telling.status = DRAFT
            telling.error = None
        except Exception as exc:  # noqa: BLE001 - the reason is the point
            # The recording is gone either way, but the telling stays and says
            # what went wrong. Losing the transcript silently would be worse.
            telling.status = FAILED
            telling.error = (str(exc) or exc.__class__.__name__)[:500]

        await db.commit()


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
        # Re-querying returns the identity-mapped object, whose segment
        # collection is whatever was loaded last. After a merge or a delete
        # that collection is stale, so force it to be rebuilt from the rows.
        .execution_options(populate_existing=True)
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
    _store_segments(db, telling, current_user.id, proposed)
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling.id))


@router.patch(
    "/tellings/{telling_id}",
    response_model=TellingResponse,
    summary="Edit a telling's transcript",
    description="Replace the transcript and re-split it into proposed memories.",
)
async def update_telling_transcript(
    telling_id: UUID,
    payload: TellingTranscriptUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Replace the transcript and start the split over.

    Refused once the telling is committed: replacing the segments would orphan
    the memories they produced. Undo the commit first, then re-split.
    """
    telling = await _load_draft_telling(db, current_user.id, telling_id)

    telling.raw_transcript = payload.raw_transcript

    # The old split described the old wording, so all of it goes rather than
    # being patched into something that no longer matches the transcript.
    for segment in list(telling.segments):
        await db.delete(segment)
    await db.flush()

    proposed = await segment_transcript(payload.raw_transcript)
    _store_segments(db, telling, current_user.id, proposed)
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling_id))


@router.post(
    "/tellings/voice",
    response_model=TellingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tell a story out loud",
    description="Upload a recording; it is transcribed and split in the background.",
)
async def capture_voice_telling(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Accept the recording and hand the slow part to a background task."""
    audio_bytes = await audio.read()

    telling = Telling(
        user_id=current_user.id,
        raw_transcript="",
        input_type="voice",
        status=TRANSCRIBING,
    )
    db.add(telling)
    await db.commit()

    background_tasks.add_task(
        _process_voice_telling,
        str(telling.id),
        str(current_user.id),
        audio_bytes,
    )

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


def _store_segments(
    db: AsyncSession, telling: Telling, user_id, proposed: SegmentationResult
) -> None:
    """Write a segmentation result onto a telling as its draft segments."""
    # The period the account is about belongs to the telling rather than to any
    # one memory, so it is stored once here and inherited by the undated.
    telling.frame_label = proposed.frame_label
    telling.frame_date = proposed.frame_date

    for ordinal, segment in enumerate(proposed.segments):
        structured = segment.structured
        db.add(
            TellingSegment(
                telling_id=telling.id,
                user_id=user_id,
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


async def _load_draft_telling(db: AsyncSession, user_id, telling_id) -> Telling:
    """Load a telling whose segments can still be reshaped.

    A committed telling's segments are already memories, so moving their
    boundaries would orphan those memories and leave every segment pointing at
    something that no longer matches its text.
    """
    telling = await _load_telling(db, user_id, telling_id)
    if telling.status == COMMITTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This telling has been committed; its segments are already "
                "memories. Undo the commit first."
            ),
        )
    return telling


def _renumber(telling: Telling) -> None:
    """Close any gaps so ordinals always run 0..n-1."""
    for index, segment in enumerate(
        sorted(telling.segments, key=lambda item: item.ordinal)
    ):
        segment.ordinal = index


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
    if (
        payload.date_precision is not None
        and payload.date_precision not in DATE_PRECISIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"date_precision must be one of {sorted(DATE_PRECISIONS)}",
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

    # Dates go through model_fields_set so an explicit null clears a field while
    # an omitted one is left alone — the difference between "no date" and "I did
    # not touch the date".
    provided = payload.model_fields_set
    for field in ("event_date", "event_date_end", "date_precision", "date_label"):
        if field in provided:
            setattr(segment, field, getattr(payload, field))

    # Reassign rather than mutate: in-place JSON changes are not detected.
    content = dict(segment.structured_content or {})
    if payload.title is not None:
        content["title"] = payload.title
    if payload.summary is not None:
        content["summary"] = payload.summary
    segment.structured_content = content

    await db.commit()

    return _segment_response(segment)


@router.get(
    "/tellings/{telling_id}/memories",
    response_model=list[MemoryResponse],
    summary="List the memories a telling produced",
    description="The memories this telling created, for review or for undoing a commit.",
)
async def list_telling_memories(
    telling_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[MemoryResponse]:
    """The memories this telling created, in the order it told them."""
    telling = await _load_telling(db, current_user.id, telling_id)

    ordered_ids = [
        segment.memory_id for segment in telling.segments if segment.memory_id
    ]
    if not ordered_ids:
        return []

    result = await db.execute(
        select(Memory).where(
            Memory.id.in_(ordered_ids), Memory.user_id == current_user.id
        )
    )
    by_id = {memory.id: memory for memory in result.scalars().all()}

    # Narrative order, not creation order: the segments know the sequence, and
    # commit-time timestamps can land in the same instant.
    return [
        _memory_response(by_id[memory_id], unlocked_ids)
        for memory_id in ordered_ids
        if memory_id in by_id
    ]


@router.delete(
    "/tellings/{telling_id}/memories",
    response_model=TellingResponse,
    summary="Delete the memories a telling produced",
    description="Undo a commit: remove its memories and return the telling to draft.",
)
async def delete_telling_memories(
    telling_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Undo a commit, keeping the telling and its transcript.

    The segments keep their text and dates, so the telling can be corrected and
    committed again rather than retold from scratch.
    """
    telling = await _load_telling(db, current_user.id, telling_id)

    memory_ids = [
        segment.memory_id for segment in telling.segments if segment.memory_id
    ]
    if memory_ids:
        result = await db.execute(
            select(Memory).where(
                Memory.id.in_(memory_ids), Memory.user_id == current_user.id
            )
        )
        for memory in result.scalars().all():
            await db.delete(memory)

    for segment in telling.segments:
        segment.memory_id = None

    # Back to a draft. The transcript is untouched, so this is a step back
    # rather than a loss.
    telling.status = DRAFT
    await db.flush()
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling_id))


@router.post(
    "/tellings/{telling_id}/segments/merge",
    response_model=TellingResponse,
    summary="Merge adjacent segments",
    description="Join two or more adjacent proposed memories into one.",
)
async def merge_segments_endpoint(
    telling_id: UUID,
    payload: TellingSegmentMerge,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Merge adjacent segments, then close the gap in the ordinals."""
    telling = await _load_draft_telling(db, current_user.id, telling_id)

    by_id = {segment.id: segment for segment in telling.segments}
    chosen = [by_id.get(segment_id) for segment_id in payload.segment_ids]
    if any(segment is None for segment in chosen):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
        )

    ordered = sorted(chosen, key=lambda segment: segment.ordinal)
    expected = list(range(ordered[0].ordinal, ordered[0].ordinal + len(ordered)))
    if [segment.ordinal for segment in ordered] != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only adjacent segments can be merged",
        )

    # The first segment keeps its structured content. The joined text is the
    # user's to re-title; re-deriving it would mean another model call, and the
    # text they can see is now different from what it described anyway.
    keeper = ordered[0]
    keeper.text = " ".join(segment.text for segment in ordered)
    for segment in ordered[1:]:
        await db.delete(segment)
    await db.flush()

    _renumber(await _load_telling(db, current_user.id, telling_id))
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling_id))


@router.delete(
    "/tellings/{telling_id}/segments/{segment_id}",
    response_model=TellingResponse,
    summary="Delete a proposed segment",
    description="Remove a proposed memory from the draft and renumber the rest.",
)
async def delete_segment_endpoint(
    telling_id: UUID,
    segment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Drop a segment that should not become a memory."""
    telling = await _load_draft_telling(db, current_user.id, telling_id)
    segment = next(
        (item for item in telling.segments if item.id == segment_id), None
    )
    if segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
        )

    await db.delete(segment)
    await db.flush()
    _renumber(await _load_telling(db, current_user.id, telling_id))
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling_id))


@router.post(
    "/tellings/{telling_id}/segments/reorder",
    response_model=TellingResponse,
    summary="Reorder proposed segments",
    description="Apply a new narrative order to the draft.",
)
async def reorder_segments_endpoint(
    telling_id: UUID,
    payload: TellingSegmentReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Set the order the segments should be read in."""
    telling = await _load_draft_telling(db, current_user.id, telling_id)

    by_id = {segment.id: segment for segment in telling.segments}
    # A partial list would leave the rest in an arbitrary place, so the order
    # has to account for every segment exactly once.
    if len(payload.segment_ids) != len(by_id) or set(payload.segment_ids) != set(
        by_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The order must list every segment exactly once",
        )

    for index, segment_id in enumerate(payload.segment_ids):
        by_id[segment_id].ordinal = index

    await db.commit()
    return _telling_response(await _load_telling(db, current_user.id, telling_id))


@router.post(
    "/tellings/{telling_id}/segments/{segment_id}/split",
    response_model=TellingResponse,
    summary="Split a proposed segment",
    description="Cut one proposed memory into two at a character offset.",
)
async def split_segment_endpoint(
    telling_id: UUID,
    segment_id: UUID,
    payload: TellingSegmentSplit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TellingResponse:
    """Cut a segment's text in two, keeping the first half where it was."""
    telling = await _load_draft_telling(db, current_user.id, telling_id)
    segment = next(
        (item for item in telling.segments if item.id == segment_id), None
    )
    if segment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found"
        )

    if payload.at >= len(segment.text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The split point is past the end of the text",
        )

    head = segment.text[: payload.at].strip()
    tail = segment.text[payload.at :].strip()
    if not head or not tail:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both halves need some text",
        )

    for other in telling.segments:
        if other.ordinal > segment.ordinal:
            other.ordinal += 1
    segment.text = head

    # The new half starts blank. Copying the first half's title and date would
    # describe text it no longer contains.
    db.add(
        TellingSegment(
            telling_id=telling.id,
            user_id=current_user.id,
            ordinal=segment.ordinal + 1,
            text=tail,
            status=PROPOSED,
        )
    )
    await db.flush()
    await db.commit()

    return _telling_response(await _load_telling(db, current_user.id, telling_id))


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
