"""Entity read routes: people, places and organizations.

Entities are first-class (see ``app/db/entities.py``). Every response here is
privacy-filtered: an entity is only visible if the user has at least one
**non-locked** memory mentioning it. Counts are computed from visible mentions
rather than the denormalized column, which includes locked memories.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from uuid import UUID

from app.db import get_db, User
from app.db.entities import (
    FIRST_CLASS_KINDS,
    count_entities_by_kind,
    get_entity_detail,
    list_entities,
)
from app.dependencies import get_current_user
from app.models.schemas import (
    EntityDetail,
    EntityListResponse,
    EntityMemoryRef,
    EntitySummary,
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

    summary = _summary(entity, visible_count)
    return EntityDetail(
        **summary.model_dump(),
        aliases=aliases,
        memories=memories,
    )
