"""Entity resolution: turning mentions into canonical entities.

This module also owns the hand edits: a rename, a description, an address. The
guards there are the same ones the automatic path uses — an alias must resolve
to exactly one entity, and the matching key must stay in step with the name.


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

from app.db.models import (
    Entity,
    EntityAlias,
    EntityMerge,
    EntitySplit,
    Memory,
    MemoryEntity,
)

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


# What a hand edit can change, and the sentinel that says "leave this alone".
# ``None`` is a real value here (it clears a description), so it cannot mean
# "omitted" — the sentinel does.
_UNSET = object()


async def update_entity(
    db: AsyncSession,
    user_id: str,
    entity_id: str,
    *,
    canonical_name=_UNSET,
    description=_UNSET,
    address=_UNSET,
) -> Entity:
    """Edit an entity's name, description or address by hand.

    Correcting the name is the point: extraction guesses a place's name from one
    person's memory of it, and the user is the authority on what it is called
    and where it is.

    Renaming keeps the old spelling as an alias, so the memories still carrying
    it resolve here rather than forking a second entity. It refuses a name
    already owned by another live entity of the same kind — that is a merge, and
    a merge is reversible where this is not.
    """
    entity = await _load_owned_entity(db, user_id, entity_id)
    if entity is None or entity.merged_into_id is not None:
        raise ValueError("Entity not found")

    if canonical_name is not _UNSET:
        cleaned = (canonical_name or "").strip()[:255]
        if not cleaned:
            raise ValueError("A name is required")
        if normalize_name(cleaned) != entity.normalized_name:
            await _ensure_name_is_free(db, user_id, entity, cleaned)
            old_name = entity.canonical_name
            await _drop_alias(db, user_id, entity, old_name)
            entity.canonical_name = cleaned
            entity.normalized_name = normalize_name(cleaned)
            await _record_alias(db, user_id, entity, old_name, source="user")

    if description is not _UNSET:
        entity.description = (description.strip() or None) if description else None

    if address is not _UNSET:
        if address is not None and entity.kind != "place":
            raise ValueError("An address belongs to a place")
        clean_address = (address or "").strip()
        attributes = dict(entity.attributes or {})
        if clean_address:
            attributes["address"] = clean_address
        else:
            attributes.pop("address", None)
        # Reassign rather than mutate: a JSON column only marks itself dirty on
        # assignment, so an in-place edit would never be saved.
        entity.attributes = attributes

    await db.commit()
    await db.refresh(entity)
    return entity


async def _ensure_name_is_free(
    db: AsyncSession, user_id: str, entity: Entity, name: str
) -> None:
    """Refuse a name another live entity of this kind already answers to."""
    taken = await find_entity_by_alias(
        db, user_id, entity.kind, normalize_name(name)
    )
    if taken is not None and str(taken.id) != str(entity.id):
        raise ValueError("Another entity already has that name")


async def _drop_alias(
    db: AsyncSession, user_id: str, entity: Entity, alias: str
) -> None:
    """Remove one spelling, freeing its matching key.

    Flushed immediately: the same key is re-added by ``_record_alias`` below,
    and with autoflush off the insert would otherwise race the delete and trip
    the unique index.
    """
    result = await db.execute(
        select(EntityAlias)
        .where(EntityAlias.user_id == user_id)
        .where(EntityAlias.entity_id == entity.id)
        .where(EntityAlias.normalized_alias == normalize_name(alias))
    )
    for row in result.scalars().all():
        await db.delete(row)
    await db.flush()


async def _record_alias(
    db: AsyncSession,
    user_id: str,
    entity: Entity,
    alias: str,
    source: str = "user",
) -> None:
    """Keep a spelling for this entity, if it is not already kept."""
    normalized = normalize_name(alias)
    if not normalized:
        return
    existing = await db.execute(
        select(EntityAlias)
        .where(EntityAlias.user_id == user_id)
        .where(EntityAlias.entity_id == entity.id)
        .where(EntityAlias.normalized_alias == normalized)
    )
    if existing.scalars().first() is not None:
        return
    db.add(
        EntityAlias(
            user_id=user_id,
            entity_id=entity.id,
            alias=alias.strip()[:255],
            normalized_alias=normalized,
            kind=entity.kind,
            source=source,
        )
    )


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


def extract_parent_links(
    structured_content: dict | None,
) -> list[tuple[str, str]]:
    """Pull containment hints out of structured_content.

    Returns ``(child_name, parent_name)`` pairs from ``metadata.parent`` on
    *place* entities. People and organizations are not nested this way, and a
    self-referential hint is ignored.
    """
    if not isinstance(structured_content, dict):
        return []

    raw = structured_content.get("entities")
    if not isinstance(raw, list):
        return []

    links: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "place":
            continue
        child = item.get("value")
        metadata = item.get("metadata")
        if not child or not isinstance(metadata, dict):
            continue
        parent = metadata.get("parent")
        if not parent:
            continue
        if normalize_name(str(child)) == normalize_name(str(parent)):
            continue
        links.append((str(child), str(parent)))

    return links


async def _find_or_create_entity(
    db: AsyncSession, user_id: str, kind: str, name: str
) -> Entity:
    """Return the entity for this name, creating it (and its alias) if new.

    Unlike :func:`apply_mentions`, this records no mention -- used for
    resolving a parent that may not be mentioned in the memory itself.
    """
    normalized = normalize_name(name)
    entity = await find_entity_by_alias(db, user_id, kind, normalized)
    if entity is not None:
        return entity

    entity = Entity(
        user_id=user_id,
        kind=kind,
        canonical_name=name.strip()[:255],
        normalized_name=normalized,
        attributes={},
        mention_count=0,
    )
    db.add(entity)
    await db.flush()

    db.add(
        EntityAlias(
            user_id=user_id,
            entity_id=entity.id,
            alias=name.strip()[:255],
            normalized_alias=normalized,
            kind=kind,
            source="llm",
        )
    )
    await db.flush()
    return entity


async def _resolve_parent_links(
    db: AsyncSession,
    user_id: str,
    structured_content: dict | None,
) -> None:
    """Set parent_entity_id for place entities with a containment hint.

    The parent is found-or-created (it need not be mentioned itself). A link is
    skipped when it would create a cycle, so two places that each claim the
    other as parent cannot both be linked.
    """
    for child_name, parent_name in extract_parent_links(structured_content):
        child = await _find_or_create_entity(db, user_id, "place", child_name)
        parent = await _find_or_create_entity(db, user_id, "place", parent_name)

        if child is None or parent is None or str(parent.id) == str(child.id):
            continue

        # Refuse a link that would close a loop back onto the child.
        if await _would_create_cycle(
            db, child_id=str(child.id), parent_id=str(parent.id)
        ):
            continue

        child.parent_entity_id = parent.id
        # Flush so the next iteration's cycle check sees this link. Sessions
        # here run with autoflush off, so an unflushed assignment would be
        # invisible and mutual parents would both be accepted.
        await db.flush()

    await db.flush()


async def _would_create_cycle(
    db: AsyncSession, child_id: str, parent_id: str
) -> bool:
    """True if linking child under parent would form a cycle."""
    # Walk up from the proposed parent; if we reach the child, it is a cycle.
    seen = set()
    current = parent_id
    while current and current not in seen:
        if current == child_id:
            return True
        seen.add(current)
        result = await db.execute(
            select(Entity.parent_entity_id).where(Entity.id == current)
        )
        next_id = result.scalar_one_or_none()
        current = str(next_id) if next_id else None
    return False
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

    # Containment hints ("a cafe in Denver") are resolved after the entities
    # exist, since a parent may not itself be mentioned.
    await _resolve_parent_links(db, user_id, structured_content)

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


# ---------------------------------------------------------------------------
# Read path
#
# Privacy is derived, never stored on the entity: a person is only as visible
# as the memories that mention them. Every read below therefore joins through
# ``memories`` and excludes locked ones, so an entity that appears solely in
# private memories cannot leak via a list, a count, or a direct fetch.
# ---------------------------------------------------------------------------


def _visible_mention_filter(user_id: str, unlocked_ids: Iterable[str]):
    """SQLAlchemy conditions identifying a *visible* mention.

    A mention is visible when its memory is not private, or is private but
    unlocked for this session.
    """
    unlocked = {str(i) for i in unlocked_ids}
    conditions = [MemoryEntity.user_id == user_id]

    if unlocked:
        conditions.append(
            (Memory.is_private.is_(False)) | (MemoryEntity.memory_id.in_(unlocked))
        )
    else:
        conditions.append(Memory.is_private.is_(False))

    return conditions


async def list_entities(
    db: AsyncSession,
    user_id: str,
    kind: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    unlocked_ids: Iterable[str] = (),
) -> tuple[list[tuple[Entity, int]], int]:
    """Return visible entities with their visible mention counts.

    The count is computed per query rather than read from the denormalized
    column, because the stored count includes locked memories.
    """
    conditions = _visible_mention_filter(user_id, unlocked_ids)

    base = (
        select(Entity, func.count(MemoryEntity.id).label("visible_count"))
        .join(MemoryEntity, MemoryEntity.entity_id == Entity.id)
        .join(Memory, Memory.id == MemoryEntity.memory_id)
        .where(Entity.user_id == user_id)
        .where(Entity.merged_into_id.is_(None))
        .where(*conditions)
        .group_by(Entity.id)
    )
    if kind:
        base = base.where(Entity.kind == kind)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = int(count_result.scalar_one())

    stmt = (
        base.order_by(
            func.count(MemoryEntity.id).desc(),
            Entity.canonical_name.asc(),
            Entity.id,
        )
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rows = [(entity, int(count)) for entity, count in result.all()]
    return rows, total


async def get_entity_detail(
    db: AsyncSession,
    user_id: str,
    entity_id: str,
    unlocked_ids: Iterable[str] = (),
) -> Optional[tuple[Entity, int, list[str], list[tuple[MemoryEntity, Memory]]]]:
    """Return an entity plus aliases and *visible* mentioning memories.

    Returns None when the entity does not exist for this user or is visible
    nowhere (i.e. every mentioning memory is locked), so it cannot be reached
    by guessing an id.
    """
    result = await db.execute(
        select(Entity)
        .where(Entity.id == entity_id)
        .where(Entity.user_id == user_id)
        .where(Entity.merged_into_id.is_(None))
    )
    entity = result.scalars().first()
    if entity is None:
        return None

    conditions = _visible_mention_filter(user_id, unlocked_ids)
    mention_result = await db.execute(
        select(MemoryEntity, Memory)
        .join(Memory, Memory.id == MemoryEntity.memory_id)
        .where(MemoryEntity.entity_id == entity.id)
        .where(*conditions)
        .order_by(Memory.event_date.desc().nullslast(), Memory.created_at.desc())
    )
    rows = [(mention, memory) for mention, memory in mention_result.all()]

    if not rows:
        # Mentioned only in locked memories: treat as not found.
        return None

    alias_result = await db.execute(
        select(EntityAlias.alias)
        .where(EntityAlias.entity_id == entity.id)
        .order_by(EntityAlias.alias.asc())
    )
    aliases = [alias for alias in alias_result.scalars().all()]

    return entity, len(rows), aliases, rows


async def count_entities_by_kind(
    db: AsyncSession,
    user_id: str,
    unlocked_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Count visible entities per kind, for nav badges."""
    conditions = _visible_mention_filter(user_id, unlocked_ids)

    stmt = (
        select(Entity.kind, func.count(func.distinct(Entity.id)))
        .join(MemoryEntity, MemoryEntity.entity_id == Entity.id)
        .join(Memory, Memory.id == MemoryEntity.memory_id)
        .where(Entity.user_id == user_id)
        .where(Entity.merged_into_id.is_(None))
        .where(*conditions)
        .group_by(Entity.kind)
    )
    result = await db.execute(stmt)

    counts = {kind: 0 for kind in FIRST_CLASS_KINDS}
    for kind, count in result.all():
        counts[str(kind)] = int(count)
    return counts


async def find_related_memories(
    db: AsyncSession,
    user_id: str,
    memory_id: str,
    limit: int = 5,
    unlocked_ids: Iterable[str] = (),
) -> list[tuple[Memory, list[str], int]]:
    """Find memories that share first-class entities with this one.

    Ranked by the number of shared entities, then by most recent. Returns
    ``(memory, shared_entity_names, shared_count)``.

    Derived on read rather than stored: this works retroactively (unlike the
    old embedding-dependent ``related_memory_ids``), never goes stale, and is
    explainable because the caller can show *why* two memories are related.

    Locked memories are excluded in both directions: the source memory must be
    visible for this to return anything, and locked candidates are omitted.
    """
    unlocked = {str(i) for i in unlocked_ids}

    # The source must exist, belong to the user, and be visible.
    source_result = await db.execute(
        select(Memory)
        .where(Memory.id == memory_id)
        .where(Memory.user_id == user_id)
    )
    source = source_result.scalars().first()
    if source is None:
        return []
    if source.is_private and str(source.id) not in unlocked:
        return []

    source_entities = {
        str(row)
        for row in (
            await db.execute(
                select(MemoryEntity.entity_id).where(
                    MemoryEntity.memory_id == memory_id
                )
            )
        ).scalars().all()
    }
    if not source_entities:
        return []

    conditions = _visible_mention_filter(user_id, unlocked)

    # Count, per candidate memory, how many of the source's entities it shares.
    shared_rows = await db.execute(
        select(
            MemoryEntity.memory_id,
            Entity.canonical_name,
        )
        .join(Entity, Entity.id == MemoryEntity.entity_id)
        .join(Memory, Memory.id == MemoryEntity.memory_id)
        .where(MemoryEntity.entity_id.in_(source_entities))
        .where(MemoryEntity.memory_id != memory_id)
        .where(*conditions)
    )

    grouped: dict[str, list[str]] = {}
    for candidate_id, entity_name in shared_rows.all():
        grouped.setdefault(str(candidate_id), [])
        if entity_name not in grouped[str(candidate_id)]:
            grouped[str(candidate_id)].append(entity_name)

    if not grouped:
        return []

    candidate_ids = list(grouped.keys())
    memories_result = await db.execute(
        select(Memory).where(Memory.id.in_(candidate_ids))
    )
    memories_by_id = {str(m.id): m for m in memories_result.scalars().all()}

    ranked = []
    for candidate_id, names in grouped.items():
        memory = memories_by_id.get(candidate_id)
        if memory is None:
            continue
        ranked.append((memory, sorted(names), len(names)))

    # Most shared entities first, then most recent as a tiebreak.
    ranked.sort(
        key=lambda item: (
            -item[2],
            -(as_utc_or_min(item[0].event_date, item[0].created_at).timestamp()),
        )
    )
    return ranked[:limit]


def as_utc_or_min(event_date, created_at):
    """Sort helper: prefer the event date, falling back to creation time."""
    from app.db.datetime_utils import as_utc

    value = event_date or created_at
    normalized = as_utc(value)
    if normalized is None:
        from datetime import datetime, timezone

        return datetime.min.replace(tzinfo=timezone.utc)
    return normalized


# ---------------------------------------------------------------------------
# Merging
#
# Merging folds a source entity into a target. The source row is never deleted
# -- it becomes a tombstone (merged_into_id set) that every read filters out.
# The exact rows that moved are recorded, so undo restores precisely those and
# nothing else.
# ---------------------------------------------------------------------------


async def _load_owned_entity(
    db: AsyncSession, user_id: str, entity_id: str
) -> Optional[Entity]:
    """Load a live entity owned by the user, or None."""
    result = await db.execute(
        select(Entity)
        .where(Entity.id == entity_id)
        .where(Entity.user_id == user_id)
    )
    return result.scalars().first()


async def merge_entities(
    db: AsyncSession,
    user_id: str,
    source_id: str,
    target_id: str,
) -> EntityMerge:
    """Fold ``source`` into ``target``, recording an undoable audit record.

    Raises ValueError when the merge is not permitted: same entity, different
    owners, different kinds, an already-merged source, or an unknown entity.
    """
    if str(source_id) == str(target_id):
        raise ValueError("Cannot merge an entity into itself")

    source = await _load_owned_entity(db, user_id, source_id)
    target = await _load_owned_entity(db, user_id, target_id)

    if source is None or target is None:
        raise ValueError("Entity not found")

    if source.merged_into_id is not None:
        raise ValueError("Source entity is already merged")

    if target.merged_into_id is not None:
        raise ValueError("Target entity is itself merged")

    # Kind is part of identity: a person "Paris" is not the city "Paris".
    if source.kind != target.kind:
        raise ValueError("Cannot merge entities of different kinds")

    # --- Move mentions.
    mention_result = await db.execute(
        select(MemoryEntity).where(MemoryEntity.entity_id == source.id)
    )
    moved_mentions = mention_result.scalars().all()
    moved_mention_ids = [str(m.id) for m in moved_mentions]
    for mention in moved_mentions:
        mention.entity_id = target.id

    # --- Move aliases, skipping any the target already has (the unique index
    # on (user_id, kind, normalized_alias) would reject duplicates). A skipped
    # alias stays on the source so an undo can still find it.
    alias_result = await db.execute(
        select(EntityAlias).where(EntityAlias.entity_id == source.id)
    )
    source_aliases = alias_result.scalars().all()

    target_alias_result = await db.execute(
        select(EntityAlias.normalized_alias).where(EntityAlias.entity_id == target.id)
    )
    target_aliases = {row for row in target_alias_result.scalars().all()}

    moved_alias_ids = []
    for alias in source_aliases:
        if alias.normalized_alias in target_aliases:
            # Already covered by the target; removing it outright would make
            # the undo impossible, so leave it attached to the tombstone.
            continue
        alias.entity_id = target.id
        moved_alias_ids.append(str(alias.id))

    # --- Tombstone the source and audit the move.
    source.merged_into_id = target.id

    merge = EntityMerge(
        user_id=user_id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        moved_mention_ids=moved_mention_ids,
        moved_alias_ids=moved_alias_ids,
    )
    db.add(merge)
    await db.flush()

    await _recompute_mention_stats(db, source)
    await _recompute_mention_stats(db, target)

    return merge


async def undo_merge(
    db: AsyncSession,
    user_id: str,
    merge_id: str,
) -> EntityMerge:
    """Reverse a merge, restoring exactly the rows that moved.

    The audit record is deleted on success, so an undo cannot be replayed.
    """
    result = await db.execute(
        select(EntityMerge)
        .where(EntityMerge.id == merge_id)
        .where(EntityMerge.user_id == user_id)
    )
    merge = result.scalars().first()
    if merge is None:
        raise ValueError("Merge not found or already undone")

    source = await _load_owned_entity(db, user_id, str(merge.source_entity_id))
    target = await _load_owned_entity(db, user_id, str(merge.target_entity_id))
    if source is None or target is None:
        raise ValueError("Entity not found")

    # --- Move the recorded mentions back.
    if merge.moved_mention_ids:
        moved = await db.execute(
            select(MemoryEntity).where(MemoryEntity.id.in_(merge.moved_mention_ids))
        )
        for mention in moved.scalars().all():
            mention.entity_id = source.id

    # --- Move the recorded aliases back.
    if merge.moved_alias_ids:
        aliases = await db.execute(
            select(EntityAlias).where(EntityAlias.id.in_(merge.moved_alias_ids))
        )
        for alias in aliases.scalars().all():
            alias.entity_id = source.id

    source.merged_into_id = None
    await db.delete(merge)
    await db.flush()

    await _recompute_mention_stats(db, source)
    await _recompute_mention_stats(db, target)

    return merge


async def split_entity(
    db: AsyncSession,
    user_id: str,
    entity_id: str,
    mention_ids: Sequence[str],
    new_name: str,
) -> EntitySplit:
    """Move chosen mentions off an entity onto a new one of the same kind.

    For the damage a merge cannot cause and an undo cannot reach: mentions that
    were never merged, but resolved to the same entity in the first place. Two
    Daves read as one.

    Raises ValueError when the split is not permitted: no mentions chosen, a
    missing name, an unknown or already-merged entity, or a mention that does
    not belong to it.
    """
    name = (new_name or "").strip()
    if not name:
        raise ValueError("A name is required for the new entity")

    chosen = [str(value) for value in mention_ids]
    if not chosen:
        raise ValueError("Choose at least one memory to move")

    source = await _load_owned_entity(db, user_id, entity_id)
    if source is None:
        raise ValueError("Entity not found")
    if source.merged_into_id is not None:
        raise ValueError("This entity has been merged; undo that first")

    mentions = (
        (
            await db.execute(
                select(MemoryEntity)
                .where(MemoryEntity.id.in_(chosen))
                .where(MemoryEntity.entity_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    if len(mentions) != len(set(chosen)):
        raise ValueError("Some of those memories are not on this entity")

    new_entity = Entity(
        user_id=user_id,
        kind=source.kind,
        canonical_name=name,
        normalized_name=normalize_name(name),
        mention_count=0,
    )
    db.add(new_entity)
    await db.flush()

    for mention in mentions:
        mention.entity_id = new_entity.id

    # Sessions run with autoflush off, so the move above is invisible to the
    # query below until it is flushed.
    await db.flush()

    # An alias is a way the name has been written, so it moves only when every
    # mention that spelt it moved too. Otherwise the memories left behind would
    # lose the spelling that reaches this entity.
    remaining = (
        (
            await db.execute(
                select(MemoryEntity).where(MemoryEntity.entity_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    moved_forms = {normalize_name(mention.surface_form) for mention in mentions}
    kept_forms = {normalize_name(mention.surface_form) for mention in remaining}

    aliases = (
        (
            await db.execute(
                select(EntityAlias).where(EntityAlias.entity_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    moved_alias_ids = []
    for alias in aliases:
        if (
            alias.normalized_alias in moved_forms
            and alias.normalized_alias not in kept_forms
        ):
            alias.entity_id = new_entity.id
            moved_alias_ids.append(str(alias.id))

    # The chosen name has to resolve to the new entity, or the very next
    # memory spelt that way would attach to the old one again.
    normalised = normalize_name(name)
    if await find_entity_by_alias(db, user_id, source.kind, normalised) is None:
        db.add(
            EntityAlias(
                user_id=user_id,
                entity_id=new_entity.id,
                alias=name,
                normalized_alias=normalised,
                kind=source.kind,
                source="user",
            )
        )

    split = EntitySplit(
        user_id=user_id,
        source_entity_id=source.id,
        new_entity_id=new_entity.id,
        moved_mention_ids=[str(mention.id) for mention in mentions],
        moved_alias_ids=moved_alias_ids,
    )
    db.add(split)
    await db.flush()

    await _recompute_mention_stats(db, source)
    await _recompute_mention_stats(db, new_entity)

    return split


async def undo_split(
    db: AsyncSession,
    user_id: str,
    split_id: str,
) -> EntitySplit:
    """Reverse a split, restoring exactly the rows that moved.

    The new entity existed only because of the split, so it goes with it. The
    audit record is deleted on success, so an undo cannot be replayed.
    """
    split = (
        (
            await db.execute(
                select(EntitySplit)
                .where(EntitySplit.id == split_id)
                .where(EntitySplit.user_id == user_id)
            )
        )
        .scalars()
        .first()
    )
    if split is None:
        raise ValueError("Split not found or already undone")

    source = await _load_owned_entity(db, user_id, str(split.source_entity_id))
    target = await _load_owned_entity(db, user_id, str(split.new_entity_id))
    if source is None or target is None:
        raise ValueError("Entity not found")

    if split.moved_mention_ids:
        moved = await db.execute(
            select(MemoryEntity).where(MemoryEntity.id.in_(split.moved_mention_ids))
        )
        for mention in moved.scalars().all():
            mention.entity_id = source.id

    if split.moved_alias_ids:
        aliases = await db.execute(
            select(EntityAlias).where(EntityAlias.id.in_(split.moved_alias_ids))
        )
        for alias in aliases.scalars().all():
            alias.entity_id = source.id

    # Flush before deleting the new entity. Its relationship is cascade
    # "all, delete-orphan", and without this the cascade reads a stale
    # collection and deletes the mentions that were just moved back.
    await db.flush()

    # Anything still on the new entity arrived with the split.
    orphans = await db.execute(
        select(EntityAlias).where(EntityAlias.entity_id == target.id)
    )
    for alias in orphans.scalars().all():
        await db.delete(alias)

    await db.delete(target)
    await db.delete(split)
    await db.flush()

    await _recompute_mention_stats(db, source)

    return split


async def suggest_merges(
    db: AsyncSession,
    user_id: str,
    unlocked_ids: Iterable[str] = (),
    limit: int = 50,
) -> list[tuple[Entity, Entity, str]]:
    """Suggest entity pairs that may be the same thing.

    Since only exact names auto-link, near-matches stay separate on purpose.
    These are the candidates worth a human's confirmation, e.g. one name being
    a prefix of another ("Sarah" / "Sarah Smith") within the same kind. Never
    merges automatically -- the caller offers them for the user to accept.
    """
    conditions = _visible_mention_filter(user_id, unlocked_ids)

    result = await db.execute(
        select(Entity, func.count(MemoryEntity.id).label("visible_count"))
        .join(MemoryEntity, MemoryEntity.entity_id == Entity.id)
        .join(Memory, Memory.id == MemoryEntity.memory_id)
        .where(Entity.user_id == user_id)
        .where(Entity.merged_into_id.is_(None))
        .where(*conditions)
        .group_by(Entity.id)
    )
    rows = [(entity, int(count)) for entity, count in result.all()]

    suggestions: list[tuple[Entity, Entity, str]] = []
    for i, (first, _) in enumerate(rows):
        for second, _ in rows[i + 1 :]:
            if first.kind != second.kind:
                continue

            a = first.normalized_name
            b = second.normalized_name
            if not a or not b:
                continue

            # One name a token-prefix of the other: "sarah" vs "sarah smith".
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            if longer == shorter or longer.startswith(shorter + " "):
                # Keep the more-established entity as the merge target.
                if first.mention_count >= second.mention_count:
                    suggestions.append((second, first, "name_prefix"))
                else:
                    suggestions.append((first, second, "name_prefix"))

            if len(suggestions) >= limit:
                return suggestions

    return suggestions
