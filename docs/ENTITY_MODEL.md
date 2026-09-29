# Entity Model — People, Places & Organizations as First-Class Data

**Status:** Design (approved) · **Supersedes:** the unused `entities` table

## Problem

Entities are currently plain text buried in `memories.structured_content` JSON:

```json
{"type": "person", "value": "Dawn", "metadata": {"relation": "wife"}}
```

The `entities` table from Phase 1 exists but has **0 rows** (54 memories have
entities only as JSON). Consequences:

- "All memories mentioning Sarah" requires scanning every memory in Python.
- "Sarah", "Sarah Smith" and "my sister Sarah" are unrelated strings — we
  cannot know they are one person.
- No way to count mentions, build a relationship graph, or filter by place.
- `related_memory_ids` is always empty, so RAG linking does nothing.

## Core idea: separate the *thing* from the *mention*

| Concept | Meaning | Cardinality |
|---|---|---|
| **Entity** | The real person/place/org | One row, forever |
| **Alias** | A way its name has been written | Many per entity |
| **MemoryEntity** | One occurrence in one memory | Many per entity, many per memory |

Everything else (counts, graphs, timelines) is a query over these three.

## Schema

### `entities` — the canonical thing

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, CASCADE | every row is user-scoped |
| `kind` | String(20) | `person` \| `place` \| `organization` |
| `canonical_name` | String(255) | display name, e.g. "Sarah Smith" |
| `normalized_name` | String(255), indexed | matching key, e.g. "sarah smith" |
| `description` | Text NULL | free-text, user- or agent-written |
| `attributes` | DBJSON | kind-specific, see below |
| `parent_entity_id` | UUID FK → entities NULL | containment hierarchy |
| `mention_count` | Integer, default 0 | denormalized for fast ranking |
| `first_seen_at` | TIMESTAMP NULL | |
| `last_seen_at` | TIMESTAMP NULL | |
| `merged_into_id` | UUID FK → entities NULL | non-null ⇒ tombstone (see Merging) |
| `created_at`, `updated_at` | TIMESTAMP | |

Indexes: `(user_id, kind)`, `(user_id, normalized_name)`, `(parent_entity_id)`,
`(user_id, mention_count)`.

**`attributes` by kind** (JSONB, so adding keys needs no migration):

- `person`: `{relation, aliases_hint, born, role}`
- `place`: `{address, city, region, country, lat, lon}`
- `organization`: `{type, domain}`

### `entity_aliases` — every spelling

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, CASCADE | |
| `entity_id` | UUID FK → entities, CASCADE | |
| `alias` | String(255) | as written, e.g. "Sarah" |
| `normalized_alias` | String(255) | |
| `source` | String(20) | `llm` \| `user` |
| `created_at` | TIMESTAMP | |

Unique: `(user_id, normalized_alias)` — one alias maps to exactly one entity,
which is what makes exact auto-linking safe.

### `memory_entities` — the mentions

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users, CASCADE | |
| `memory_id` | UUID FK → memories, CASCADE | |
| `entity_id` | UUID FK → entities, CASCADE | |
| `surface_form` | String(255) | exactly what was written here |
| `role` | String(50) NULL | "brother", "colleague", "venue" |
| `snippet` | Text NULL | surrounding text for context |
| `confidence` | Float NULL | 0–1 |
| `created_at` | TIMESTAMP | |

Unique: `(memory_id, entity_id, surface_form)`.
Indexes: `(entity_id)`, `(memory_id)`, `(user_id, entity_id)`.

## Matching & merging

**Auto-link (exact only).** On capture, normalise the surface form
(lowercase, trim, collapse whitespace, strip possessive `'s`). If a matching
`entity_aliases.normalized_alias` exists for this user, attach the mention to
that entity and add the alias if new. Otherwise create a new entity.

**Confirm (everything else).** Never auto-merge initials, partial names or
nicknames. Those become a *suggestion* surfaced for the user to confirm.

**Reversible merge with audit.** Merging entity B into A:

1. Repoint B's `memory_entities` and `entity_aliases` to A.
2. Recompute A's `mention_count`, `first_seen_at`, `last_seen_at`.
3. Set `B.merged_into_id = A.id` (tombstone — B is never deleted).
4. Record the operation in `entity_merges`:

| Column | Type |
|---|---|
| `id` | UUID PK |
| `user_id` | UUID FK → users |
| `source_entity_id` | UUID FK → entities |
| `target_entity_id` | UUID FK → entities |
| `moved_mention_ids` | DBJSON — exact ids moved, so undo is precise |
| `moved_alias_ids` | DBJSON |
| `created_at` | TIMESTAMP |

Undo replays the recorded ids back to the source and clears the tombstone.
Queries always filter `merged_into_id IS NULL`, so a tombstone never surfaces.

## Privacy

**Nothing is stored about privacy on entities.** Visibility is derived, because
a person is only as visible as the memories that mention them:

> An entity is visible iff its user has at least one **non-locked** memory
> mentioning it.

- Lists, counts and search must join through `memories` and exclude locked
  memories (the existing `is_locked` / `X-Unlocked-Memory-Ids` mechanism).
- `mention_count` must be computed from *visible* mentions, so the denormalized
  column is a cache of the unlocked count, refreshed on unlock-independent
  writes and corrected at read time.

## Queries this unlocks

| Question | Query shape |
|---|---|
| Memories about Sarah | `memory_entities → memories WHERE entity_id = ?` |
| Most-mentioned people | `entities WHERE kind='person' ORDER BY mention_count DESC` |
| Who appears with Sarah | self-join `memory_entities` on `memory_id` |
| Memories in Denver (incl. its cafés) | recursive walk of `parent_entity_id` |
| Person timeline | `memory_entities` join `memories.event_date` |
| Relationship graph | co-occurrence edges between entity pairs |

This also **replaces `related_memory_ids`**: related memories become derived
(shared entities + embedding similarity) instead of a stored, staleable list.

## Migration

1. Create the three new tables plus `entity_merges`.
2. **Drop the empty legacy `entities` table** (0 rows — safe).
3. Backfill: walk `structured_content.entities` for every memory; for
   `person` / `place`, and `organization` if present, create-or-attach using
   the same matching rules. Preserve `metadata.relation` into
   `memory_entities.role` and `entities.attributes.relation`.
4. Leave `date` / `event` / `concept` entities in JSON (not first-class).
5. `entities` stays in the response payloads as a derived convenience, now
   sourced from the real tables.

## Explicitly deferred

- `entity_relations` (married_to, works_at) — co-occurrence covers most needs.
- Non-exact auto-merge via embeddings.
- Event/concept entities as first-class kinds.

## Decisions taken

- Auto-link **exact** matches only; fuzzy matches are user-confirmed.
- Merges are **reversible** with a full audit trail.
- A **browse page** for People/Places ships with this work.
- First-class kinds are **person, place, organization** only.
