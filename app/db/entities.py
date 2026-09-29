"""Entity resolution: turning mentions into canonical entities.

The model separates three things:
- ``Entity``       the real person/place/organization (one row, forever)
- ``EntityAlias``  every way its name has been written
- ``MemoryEntity`` one mention inside one memory

Linking rule: only *exact* normalized names auto-link. "Sarah" and "Sarah
Smith" deliberately stay separate entities -- merging them is a user decision
(see the merge helpers), never an automatic guess.
"""

from __future__ import annotations

import re
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Entity, EntityAlias, MemoryEntity

# Only these become first-class entities. Dates are handled by event_date;
# event/concept stay in structured_content JSON.
FIRST_CLASS_KINDS = {"person", "place", "organization"}

_WHITESPACE_RE = re.compile(r"\s+")
# Punctuation we strip from the ends, but never from inside a name so that
# "Anne-Marie" and "O'Brien" survive intact.
_EDGE_PUNCTUATION = " \t\r\n.,;:!?\"'()[]{}<>"


def normalize_name(value: str) -> str:
    """Return the matching key for a name.

    Lowercases, collapses whitespace, strips surrounding punctuation, and drops
    a trailing possessive so "Sarah's" matches "Sarah". Interior hyphens and
    apostrophes are preserved because they are part of real names.
    """
    if not value:
        return ""

    text = _WHITESPACE_RE.sub(" ", value.strip().lower())

    # Strip surrounding punctuation, including a trailing apostrophe, so
    # "(Sarah)." -> "sarah" and "Sarahs'" -> "sarahs".
    text = text.strip(_EDGE_PUNCTUATION)

    # Then drop a possessive "'s" so "Sarah's" matches "Sarah".
    if text.endswith("'s"):
        text = text[:-2]

    return text.strip(_EDGE_PUNCTUATION).strip()


async def find_entity_by_alias(
    db: AsyncSession,
    user_id: str,
    kind: str,
    normalized_alias: str,
) -> Optional[Entity]:
    """Look up a live entity for this user by exact alias, scoped to kind."""
    stmt = (
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(Entity.user_id == user_id)
        .where(Entity.kind == kind)
        .where(Entity.merged_into_id.is_(None))
        .where(EntityAlias.user_id == user_id)
        .where(EntityAlias.normalized_alias == normalized_alias)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _recompute_mention_stats(
    db: AsyncSession, entity: Entity
) -> None:
    """Refresh mention_count / first_seen / last_seen from live mentions."""
    stmt = select(
        func.count(MemoryEntity.id),
        func.min(MemoryEntity.created_at),
        func.max(MemoryEntity.created_at),
    ).where(MemoryEntity.entity_id == entity.id)
    result = await db.execute(stmt)
    count, first_seen, last_seen = result.one()

    entity.mention_count = int(count or 0)
    entity.first_seen_at = first_seen
    entity.last_seen_at = last_seen


async def recompute_entity_stats(
    db: AsyncSession, entity_ids: Iterable[str]
) -> None:
    """Recompute denormalized stats for the given entities.

    Must be called after any operation that removes mentions (e.g. deleting a
    memory), otherwise the cached ``mention_count`` drifts from reality.
    """
    ids = {str(eid) for eid in entity_ids if eid}
    if not ids:
        return

    result = await db.execute(select(Entity).where(Entity.id.in_(ids)))
    for entity in result.scalars().all():
        await _recompute_mention_stats(db, entity)

async def entity_ids_for_memory(db: AsyncSession, memory_id: str) -> list[str]:
    """Return the ids of entities mentioned in a memory."""
    result = await db.execute(
        select(MemoryEntity.entity_id).where(MemoryEntity.memory_id == memory_id)
    )
    return [str(eid) for eid in result.scalars().all()]


def extract_mentions(
    structured_content: dict | None,
) -> list[tuple[str, str, Optional[str]]]:
    """Pull first-class entity mentions out of a structured_content dict.

    Returns ``(kind, surface_form, role)`` triples. The role comes from the
    agent's ``metadata.relation`` (e.g. "wife") or ``metadata.role``.

    Dates are handled by event_date, and event/concept stay as JSON, so only
    person/place/organization are returned.
    """
    if not isinstance(structured_content, dict):
        return []

    raw = structured_content.get("entities")
    if not isinstance(raw, list):
        return []

    mentions: list[tuple[str, str, Optional[str]]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        value = item.get("value")
        if kind not in FIRST_CLASS_KINDS or not value:
            continue

        role = None
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            role = metadata.get("relation") or metadata.get("role")
        mentions.append((str(kind), str(value), str(role) if role else None))

    return mentions


async def sync_memory_entities(
    db: AsyncSession,
    user_id: str,
    memory_id: str,
    structured_content: dict | None,
) -> list[Entity]:
    """Make the mentions of a memory match its current content exactly.

    This is the single entry point for every stage that writes
    ``structured_content`` (capture, refinement, enrichment). Because
    reprocessing rewrites the whole content, this *replaces* the memory's
    mentions rather than only adding: anything no longer present is detached,
    so stale links cannot linger and counts stay truthful.

    Entities themselves are never deleted -- an entity with no remaining
    mentions simply has ``mention_count == 0``.
    """
    desired = extract_mentions(structured_content)

    # Which entities does the memory currently point at?
    previously = set(await entity_ids_for_memory(db, memory_id))

    # Drop all existing mentions for this memory; we re-add the desired set.
    existing_rows = (
        await db.execute(select(MemoryEntity).where(MemoryEntity.memory_id == memory_id))
    ).scalars().all()
    for row in existing_rows:
        await db.delete(row)
    await db.flush()

    touched = await apply_mentions(db, user_id, memory_id, desired)

    # Refresh the counts of anything that gained or lost a mention.
    affected = previously | {str(entity.id) for entity in touched}
    await recompute_entity_stats(db, affected)

    return touched


async def apply_mentions(
    db: AsyncSession,
    user_id: str,
    memory_id: str,
    mentions: Sequence[tuple[str, str, Optional[str]]],
) -> list[Entity]:
    """Attach mentions of entities to a memory, creating entities as needed.

    ``mentions`` is a sequence of ``(kind, surface_form, role)``. Only
    first-class kinds are stored. Returns the entities touched.

    Adds without removing, so it is safe to call repeatedly: an existing
    mention for the same (memory, entity, surface form) is not duplicated.
    Use :func:`sync_memory_entities` when the content has been rewritten and
    vanished mentions must be dropped.
    """
    touched: list[Entity] = []

    for kind, surface_form, role in mentions:
        if kind not in FIRST_CLASS_KINDS:
            continue
        if not surface_form or not surface_form.strip():
            continue

        normalized = normalize_name(surface_form)
        if not normalized:
            continue

        entity = await find_entity_by_alias(db, user_id, kind, normalized)

        if entity is None:
            entity = Entity(
                user_id=user_id,
                kind=kind,
                canonical_name=surface_form.strip()[:255],
                normalized_name=normalized,
                attributes={},
                mention_count=0,
            )
            db.add(entity)
            await db.flush()  # assign id

            db.add(
                EntityAlias(
                    user_id=user_id,
                    entity_id=entity.id,
                    alias=surface_form.strip()[:255],
                    normalized_alias=normalized,
                    kind=kind,
                    source="llm",
                )
            )

        # A mention is unique per (memory, entity, surface form).
        existing = await db.execute(
            select(MemoryEntity)
            .where(MemoryEntity.memory_id == memory_id)
            .where(MemoryEntity.entity_id == entity.id)
            .where(MemoryEntity.surface_form == surface_form.strip()[:255])
        )
        if existing.scalars().first() is None:
            db.add(
                MemoryEntity(
                    user_id=user_id,
                    memory_id=memory_id,
                    entity_id=entity.id,
                    surface_form=surface_form.strip()[:255],
                    role=(role[:50] if role else None),
                )
            )

        touched.append(entity)

    await db.flush()

    # Recomputed rather than incremented so idempotent replays stay correct.
    for entity in touched:
        await _recompute_mention_stats(db, entity)

    return touched
