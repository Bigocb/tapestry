---
type: Reference
title: Tapestry Data Models
description: SQLAlchemy ORM models and Pydantic schemas for memories, entities, stories, and jobs, including cross-database compatibility and the entity model.
tags: [tapestry, data-models, pydantic, sqlalchemy, schema, entities]
---

# Data Models

Tapestry has two model layers: **SQLAlchemy ORM models** for persistence
([`app/db/models.py`](../app/db/models.py)) and **Pydantic schemas** for API
validation and serialisation ([`app/models/schemas.py`](../app/models/schemas.py)).
For the entity model in depth see [`docs/ENTITY_MODEL.md`](../docs/ENTITY_MODEL.md).

## Cross-Database Compatibility

Production targets PostgreSQL + pgvector; tests and local dev use SQLite. Two
type decorators bridge the differences:

- **`GUID`** — native `UUID` on Postgres, `String(36)` on SQLite. Converts to
  string on write and back to `UUID` on read.
- **`DBJSON`** — `JSONB` on Postgres, `JSON` on SQLite.

**Id consistency rule**: model defaults return `uuid.uuid4` (a `UUID`), never
`str(uuid4())`. A str default produces a different Python type than a loaded
row, and SQLAlchemy's flush ordering then compares `UUID < str` and raises.

Postgres-only index types (`GIN`, `ivfflat`) are declared in the ORM and are
ignored on SQLite.

## Processing State Machine

```
raw → capturing → refined → enriching → enriched → ready
```

| State | Meaning |
|-------|---------|
| `raw` | Just captured |
| `capturing` | Capture/structuring in progress |
| `refined` | Refinement agent has run |
| `enriched` | Enrichment agent has run (final stage) |

Failed jobs set `<stage>_failed`. In practice the pipeline runs
capture → refined → enriched.

## ORM Models

### User

`id`, `username` (unique), `email` (unique), `password_hash`, `created_at`,
`updated_at`. Relationships: `memories`, `entities`, `stories` (cascade delete).

### Memory

| Column | Type | Notes |
|--------|------|-------|
| `id` | GUID | PK |
| `user_id` | GUID | FK → users, CASCADE |
| `raw_input` | Text | Original input |
| `input_type` | String(50) | `voice` / `text` / `form` |
| `structured_content` | DBJSON | Serialised `StructuredMemory` |
| `embedding` | String(3000) | Serialised JSON vector (see gap below) |
| `tags` | DBJSON | List of strings |
| `mood` | String(50) | Optional |
| `importance_level` | Integer | 1–10, default 5 |
| `processing_state` | String(50) | State machine |
| `related_memory_ids` | DBJSON | Legacy; related memories are now derived |
| `event_date` | TIMESTAMP | When the event happened |
| `date_precision` | String(20) | `exact` / `month` / `year` / `decade` / `range` / `unknown` |
| `event_date_end` | TIMESTAMP | Upper bound for `range` |
| `date_label` | String(120) | Human wording for fuzzy periods, e.g. "the 80s" |
| `needs_review` | Boolean | Review queue flag |
| `review_reason` | String(50) | e.g. `missing_date` |
| `is_private` | Boolean | Privacy lock |
| `entities_backfilled` | Boolean | One-time entity backfill marker |
| `created_at`, `updated_at` | TIMESTAMP | |

### Entity

The canonical person/place/organization — one row per real thing.

| Column | Notes |
|--------|-------|
| `kind` | `person` / `place` / `organization` |
| `canonical_name`, `normalized_name` | Display name and matching key |
| `attributes` | DBJSON, kind-specific |
| `parent_entity_id` | Self-FK for containment (cafe → city) |
| `mention_count`, `first_seen_at`, `last_seen_at` | Denormalized stats |
| `merged_into_id` | Non-null ⇒ tombstone; every query filters these out |

### EntityAlias

Every spelling. Unique on `(user_id, kind, normalized_alias)`, so an alias
resolves to exactly one entity — this is what makes exact auto-linking safe.
`kind` participates because a person "Paris" and the place "Paris" must coexist.

### MemoryEntity

One mention: `memory_id`, `entity_id`, `surface_form` (as written), `role`
(e.g. "wife"), `snippet`, `confidence`. Unique per
`(memory_id, entity_id, surface_form)`.

### EntityMerge

Audit record making merges reversible: `source_entity_id`, `target_entity_id`,
and `moved_mention_ids` / `moved_alias_ids` recording exactly what moved.

### Story

`title`, `narrative` (markdown), `memory_ids` (DBJSON), `story_type`.

### JobStatus

`task_type` (`refinement` / `enrichment` / `story`), `status`, `progress`,
`error`, and `overrides` — user edits captured at queue time, re-applied after
each agent stage.

## Pydantic Schemas

All use Pydantic v2. Notable conventions:

- `MemoryResponse` carries both denormalized fields and derived conveniences
  (`title`, `summary`, `people`, `location`, `is_locked`)
- `MemoryUpdate` sets `extra="forbid"`, so a misspelled field returns 422
  instead of being silently dropped. This was added after the frontend sent
  phantom `refined_text` / `importance_score` fields and lost edits silently
- `StructuredMemory` includes `date_precision`, `event_date_end` and
  `date_label` alongside `event_date`
- `EntitySummary`, `EntityDetail`, `EntityMergeRequest/Response`,
  `EntityMergeSuggestion`
- `RelatedMemory`, `RelatedMemoriesResponse`

### Validation Highlights

- Username: 3–255 chars, alphanumeric + `_`/`-`
- Password: minimum 8 characters
- `input_type`: `voice` / `text` / `form`
- `date_precision`: `exact` / `month` / `year` / `decade` / `range` / `unknown`
- `story_type`: `chronological` / `thematic` / `curated` / `digest`
- `importance_level`: 1–10

## Known Gaps

- **Embeddings** are serialised JSON in a `String(3000)` column, and similarity
  is computed in Python. A pgvector `vector` column with an ANN index is the
  intended production shape.
- **`related_memory_ids`** on `Memory` is legacy. Related memories are now
  derived on read from shared entities (see
  [`find_related_memories`](../app/db/entities.py)), which works retroactively
  and cannot go stale.
