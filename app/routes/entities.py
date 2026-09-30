"""Entity read routes: people, places and organizations.

Entities are first-class (see ``app/db/entities.py``). Every response here is
privacy-filtered: an entity is only visible if the user has at least one
**non-locked** memory mentioning it. Counts are computed from visible mentions
rather than the denormalized column, which includes locked memories.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from app.db import EntityFact, MemoryEntity, get_db, User
from app.db.entities import (
    FIRST_CLASS_KINDS,
    _load_owned_entity,
    count_entities_by_kind,
    get_entity_detail,
    list_entities,
    merge_entities,
    split_entity,
    suggest_merges,
    undo_merge,
    undo_split,
)
from app.lookup import search_places
from app.dependencies import get_current_user
from app.models.schemas import (
    EntityDetail,
    EntityFactRequest,
    EntityFactResponse,
    EntityListResponse,
    EntityMemoryRef,
    EntityMergeRequest,
    EntityMergeResponse,
    EntityMergeSuggestion,
    EntitySplitRequest,
    EntitySplitResponse,
    EntitySummary,
    LookupCandidate,
)
from app.privacy import get_unlocked_memory_ids

router = APIRouter()


def _summary(entity, visible_count: int) -> EntitySummary:
    return EntitySummary(
        id=entity.id,
        kind=entity.kind,
        canonical_name=entity.canonical_name,
        description=entity.description,
        attributes=entity.attributes,
        parent_entity_id=entity.parent_entity_id,
        mention_count=visible_count,
        first_seen_at=entity.first_seen_at,
        last_seen_at=entity.last_seen_at,
    )


@router.get(
    "/entities",
    response_model=EntityListResponse,
    summary="List entities",
    description=(
        "List the user's people, places and organizations, most mentioned "
        "first. Entities that appear only in locked memories are omitted."
    ),
)
async def get_entities(
    kind: Optional[str] = Query(
        None, description="Filter by kind: person, place or organization"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> EntityListResponse:
    """Return the current user's visible entities."""
    if kind is not None and kind not in FIRST_CLASS_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of {sorted(FIRST_CLASS_KINDS)}",
        )

    rows, total = await list_entities(
        db,
        str(current_user.id),
        kind=kind,
        limit=limit,
        offset=offset,
        unlocked_ids=unlocked_ids,
    )

    return EntityListResponse(
        items=[_summary(entity, count) for entity, count in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/entities/counts",
    summary="Count entities by kind",
    description="Lightweight endpoint for nav badges. Excludes locked-only entities.",
)
async def get_entity_counts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> dict:
    """Return visible entity counts per kind."""
    return await count_entities_by_kind(db, str(current_user.id), unlocked_ids)


@router.get(
    "/entities/merge-suggestions",
    response_model=list[EntityMergeSuggestion],
    summary="Suggest possible duplicate entities",
    description=(
        "Since only exact names auto-link, near-matches are surfaced here for "
        "confirmation. Nothing is merged automatically."
    ),
)
async def get_merge_suggestions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> list[EntityMergeSuggestion]:
    """Return entity pairs that may refer to the same thing."""
    rows = await suggest_merges(db, str(current_user.id), unlocked_ids)

    return [
        EntityMergeSuggestion(
            source=_summary(source, source.mention_count),
            target=_summary(target, target.mention_count),
            reason=reason,
        )
        for source, target, reason in rows
    ]


@router.post(
    "/entities/merge",
    response_model=EntityMergeResponse,
    summary="Merge two entities",
    description=(
        "Fold the source entity into the target: mentions and aliases move over "
        "and the source becomes a tombstone. Reversible via the returned "
        "merge_id."
    ),
)
async def merge_entities_endpoint(
    request: EntityMergeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityMergeResponse:
    """Merge one entity into another."""
    try:
        merge = await merge_entities(
            db,
            str(current_user.id),
            source_id=str(request.source_id),
            target_id=str(request.target_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    await db.commit()

    return EntityMergeResponse(
        merge_id=merge.id,
        source_id=merge.source_entity_id,
        target_id=merge.target_entity_id,
        moved_mention_count=len(merge.moved_mention_ids or []),
        moved_alias_count=len(merge.moved_alias_ids or []),
    )


@router.post(
    "/entities/merge/{merge_id}/undo",
    response_model=EntityMergeResponse,
    summary="Undo a merge",
    description="Restore exactly the mentions and aliases that moved.",
)
async def undo_merge_endpoint(
    merge_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityMergeResponse:
    """Reverse a previously applied merge."""
    try:
        merge = await undo_merge(db, str(current_user.id), str(merge_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )

    await db.commit()

    return EntityMergeResponse(
        merge_id=merge.id,
        source_id=merge.source_entity_id,
        target_id=merge.target_entity_id,
        moved_mention_count=len(merge.moved_mention_ids or []),
        moved_alias_count=len(merge.moved_alias_ids or []),
    )


# Declared last on purpose: this path would otherwise capture the static routes
# above ("/entities/counts", "/entities/merge", ...) as an entity id.
@router.post(
    "/entities/{entity_id}/split",
    response_model=EntitySplitResponse,
    summary="Split an entity",
    description=(
        "Move chosen mentions onto a new entity of the same kind. For when "
        "extraction read two things as one — which no merge undo can reach."
    ),
)
async def split_entity_endpoint(
    entity_id: UUID,
    request: EntitySplitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntitySplitResponse:
    """Pull some of an entity's memories out into a new entity."""
    # What moves is a mention, since that is what belongs to an entity. The
    # caller names memories, so they are resolved here rather than making every
    # caller learn about mentions.
    mention_rows = await db.execute(
        select(MemoryEntity)
        .where(MemoryEntity.entity_id == entity_id)
        .where(MemoryEntity.memory_id.in_([str(m) for m in request.memory_ids]))
    )
    mention_ids = [str(row.id) for row in mention_rows.scalars().all()]

    if len(mention_ids) != len(set(str(m) for m in request.memory_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Some of those memories are not on this entity",
        )

    try:
        split = await split_entity(
            db,
            str(current_user.id),
            str(entity_id),
            mention_ids,
            request.name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )

    await db.commit()

    return EntitySplitResponse(
        split_id=split.id,
        source_entity_id=split.source_entity_id,
        new_entity_id=split.new_entity_id,
        moved_mention_count=len(split.moved_mention_ids or []),
    )


@router.post(
    "/entities/split/{split_id}/undo",
    summary="Undo a split",
    description="Restore the mentions that moved and drop the entity they moved to.",
)
async def undo_split_endpoint(
    split_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reverse a previously applied split."""
    try:
        await undo_split(db, str(current_user.id), str(split_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )

    await db.commit()
    return {"detail": "Split undone."}


@router.get(
    "/entities/{entity_id}/lookup",
    response_model=list[LookupCandidate],
    summary="Look a place up outside the app",
    description="Candidate matches for this place's name. Nothing is stored.",
)
async def lookup_entity(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LookupCandidate]:
    """Offer candidates for the user to choose between.

    Several, not one: a name like "Raleigh" matches a city, a family name and
    an Australian electorate. Choosing is the user's job, and the label and
    description are what make that choice possible.
    """
    entity = await _load_owned_entity(db, str(current_user.id), str(entity_id))
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found"
        )

    # People are never looked up. Resolving a first name to a real individual
    # is unreliable and invasive, and being helpfully wrong about a friend is
    # worse than saying nothing.
    if entity.kind != "place":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only places can be looked up. A person's name is not enough "
                "to identify a real individual reliably."
            ),
        )

    return [
        LookupCandidate(
            source=match.source,
            source_id=match.source_id,
            label=match.label,
            description=match.description,
            url=match.url,
        )
        for match in await search_places(entity.canonical_name)
    ]


@router.post(
    "/entities/{entity_id}/facts",
    response_model=EntityFactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Keep a looked-up fact",
    description="Store a fact found outside the app, with where it came from.",
)
async def keep_fact(
    entity_id: UUID,
    request: EntityFactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityFactResponse:
    """Keep a candidate the user chose.

    Stored apart from the entity's own attributes, so it can never be mistaken
    for something the user said.
    """
    entity = await _load_owned_entity(db, str(current_user.id), str(entity_id))
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found"
        )

    fact = EntityFact(
        user_id=current_user.id,
        entity_id=entity.id,
        source=request.source,
        source_id=request.source_id,
        label=request.label,
        description=request.description,
        source_url=request.url,
    )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)

    return EntityFactResponse(
        id=fact.id,
        source=fact.source,
        source_id=fact.source_id,
        label=fact.label,
        description=fact.description,
        url=fact.source_url,
        fetched_at=fact.fetched_at,
    )


@router.delete(
    "/entities/{entity_id}/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a kept fact",
    description="Throw away a fact that turned out to be the wrong match.",
)
async def discard_fact(
    entity_id: UUID,
    fact_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Forget a fact found about this entity."""
    entity = await _load_owned_entity(db, str(current_user.id), str(entity_id))
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found"
        )

    fact = (
        (
            await db.execute(
                select(EntityFact)
                .where(EntityFact.id == fact_id)
                .where(EntityFact.entity_id == entity.id)
                .where(EntityFact.user_id == current_user.id)
            )
        )
        .scalars()
        .first()
    )
    if fact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found"
        )

    await db.delete(fact)
    await db.commit()


@router.get(
    "/entities/{entity_id}",
    response_model=EntityDetail,
    summary="Get an entity",
    description=(
        "Full detail for a person, place or organization: every known spelling "
        "and the visible memories mentioning it. 404 if it does not exist, "
        "belongs to someone else, or appears only in locked memories."
    ),
)
async def get_entity(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    unlocked_ids: set[str] = Depends(get_unlocked_memory_ids),
) -> EntityDetail:
    """Return full detail for one entity."""
    detail = await get_entity_detail(
        db, str(current_user.id), str(entity_id), unlocked_ids
    )

    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    entity, visible_count, aliases, rows = detail

    memories = []
    for mention, memory in rows:
        content = (
            memory.structured_content
            if isinstance(memory.structured_content, dict)
            else {}
        )
        memories.append(
            EntityMemoryRef(
                id=memory.id,
                title=content.get("title"),
                summary=content.get("summary"),
                role=mention.role,
                event_date=memory.event_date,
                date_precision=memory.date_precision,
                date_label=memory.date_label,
                created_at=memory.created_at,
            )
        )

    fact_rows = await db.execute(
        select(EntityFact)
        .where(EntityFact.entity_id == entity.id)
        .where(EntityFact.user_id == current_user.id)
        .order_by(EntityFact.fetched_at.desc())
    )
    facts = [
        EntityFactResponse(
            id=fact.id,
            source=fact.source,
            source_id=fact.source_id,
            label=fact.label,
            description=fact.description,
            url=fact.source_url,
            fetched_at=fact.fetched_at,
        )
        for fact in fact_rows.scalars().all()
    ]

    summary = _summary(entity, visible_count)
    return EntityDetail(
        **summary.model_dump(),
        aliases=aliases,
        memories=memories,
        facts=facts,
    )
