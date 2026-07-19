---
type: Reference
title: MEMIND Data Models
description: Pydantic schemas and SQLAlchemy ORM models for users, memories, entities, stories, search, and insights in MEMIND, including cross-database compatibility details.
tags: [memind, data-models, pydantic, sqlalchemy, schema]
---

# Data Models

MEMIND has two parallel model systems: **Pydantic schemas** for API validation and serialization, and **SQLAlchemy ORM models** for database persistence. This page covers both and explains their relationship.

## Processing State Machine

A memory transitions through these states:

```
raw → capturing → refined → enriching → enriched → ready
```

- `raw`: Initial state after capture — only `raw_input` and `input_type` are populated
- `capturing`: Capture Agent is running (transient, not yet implemented)
- `refined`: Structured content populated by Capture Agent
- `enriching`: Enrichment Agent is running (transient, not yet implemented)
- `enriched`: Tags, importance, and related memories added
- `ready`: Fully processed and searchable

Currently only `raw` state is set by the capture endpoint; agent transitions are not yet implemented.

## SQLAlchemy ORM Models

Defined in [`app/db/models.py`](../app/db/models.py).

### Cross-Database Compatibility

MEMIND supports both PostgreSQL (production) and SQLite (tests). Two custom type decorators handle the differences:

- **`GUID`**: Uses PostgreSQL's native `UUID` type, falls back to `String(36)` on SQLite. UUIDs are converted to strings for SQLite storage and back to `UUID` objects on read.
- **`DBJSON`**: Uses PostgreSQL's `JSONB` type for efficient JSON queries, falls back to standard `JSON` on SQLite.

> **Known limitation**: PostgreSQL-specific index types like `GIN` (for tags) and `ivfflat` (for vector similarity) are defined in the ORM but will fail on SQLite. The `test_db_setup.py` tests that use Postgres-specific features must run against a real PostgreSQL instance.

### User

| Column | Type | Notes |
|--------|------|-------|
| id | GUID (UUID/string) | Primary key, auto-generated |
| username | String(255) | Unique, indexed |
| email | String(255) | Unique, indexed |
| password_hash | String(255) | bcrypt hash |
| created_at | TIMESTAMP | Server default `now()` |
| updated_at | TIMESTAMP | Server default, auto-updates |

Relationships: `memories`, `entities`, `stories` (all cascade delete)

### Memory

| Column | Type | Notes |
|--------|------|-------|
| id | GUID | Primary key |
| user_id | GUID | FK → users.id, CASCADE |
| raw_input | Text | Original text input |
| input_type | String(50) | `'voice'`, `'text'`, or `'form'` |
| structured_content | DBJSON | Serialized `StructuredMemory` Pydantic model |
| embedding | String(3000) | Stored as JSON string; will become pgvector column |
| tags | DBJSON | JSON array of strings |
| mood | String(50) | Optional mood label |
| importance_level | Integer | 1–10, default 5 |
| processing_state | String(50) | State machine, default `'raw'` |
| related_memory_ids | DBJSON | JSON array of UUID strings |
| created_at | TIMESTAMP | Server default |
| updated_at | TIMESTAMP | Server default, auto-updates |

Indexes: `idx_memories_user_id`, `idx_memories_created_at` (btree), `idx_memories_tags` (GIN, Postgres only)

> **Note**: The `embedding` column currently uses `String(3000)` instead of pgvector's `vector` type. The PRD calls for pgvector embeddings, but the ORM model stores embeddings as JSON strings. This will need to change to a proper `vector(1536)` column when the enrichment pipeline is implemented.

### Entity

| Column | Type | Notes |
|--------|------|-------|
| id | GUID | Primary key |
| user_id | GUID | FK → users.id, CASCADE |
| memory_id | GUID | FK → memories.id, CASCADE |
| type | String(50) | `'person'`, `'place'`, `'date'`, `'event'`, `'concept'` |
| value | Text | Entity text |
| entity_metadata | DBJSON | Flexible key-value store |
| created_at | TIMESTAMP | Server default |

### Story

| Column | Type | Notes |
|--------|------|-------|
| id | GUID | Primary key |
| user_id | GUID | FK → users.id, CASCADE |
| title | String(255) | Story title |
| narrative | Text | Generated markdown narrative |
| memory_ids | DBJSON | JSON array of source memory UUIDs |
| story_type | String(50) | `'chronological'`, `'thematic'`, `'curated'`, `'digest'` |
| created_at | TIMESTAMP | Server default |
| updated_at | TIMESTAMP | Server default, auto-updates |

### JobStatus

| Column | Type | Notes |
|--------|------|-------|
| id | GUID | Primary key |
| user_id | GUID | Not a FK (no cascading) |
| memory_id | GUID | Nullable |
| task_type | String(50) | `'refinement'`, `'enrichment'`, `'story'` |
| status | String(50) | `'pending'`, `'running'`, `'completed'`, `'failed'` |
| progress | Float | 0.0–1.0 |
| error | Text | Nullable error message |
| created_at | TIMESTAMP | Server default |
| updated_at | TIMESTAMP | Server default, auto-updates |

## Pydantic Schemas

Defined in [`app/models/schemas.py`](../app/models/schemas.py). All schemas use Pydantic v2 with `Config.from_attributes = True` for ORM compatibility.

### Domain Schemas

| Schema | Domain | Purpose |
|--------|--------|---------|
| `UserCreate` | Auth | Registration input (username, email, password) |
| `UserLogin` | Auth | Login input (username, password) |
| `UserResponse` | Auth | User output (id, username, email, created_at) |
| `TokenResponse` | Auth | JWT output (access_token, token_type) |
| `MemoryCapture` | Memory | Capture input (raw_input, input_type) |
| `MemoryResponse` | Memory | Full memory output with all fields |
| `MemoryUpdate` | Memory | Partial update input |
| `StructuredMemory` | Memory | Post-capture structure (title, summary, entities, mood, tags) |
| `EntityData` | Entity | Entity input (type, value, metadata) |
| `EntityResponse` | Entity | Entity output with id and timestamps |
| `SearchQuery` | Search | Structured search (text, semantic, filters, pagination) |
| `SearchFilters` | Search | Date range, tags, mood, importance filters |
| `SearchResult` | Search | Single search result with relevance score |
| `SearchResponse` | Search | Paginated search results |
| `StoryGenerate` | Story | Story creation input (memory_ids, story_type, custom_prompt) |
| `StoryResponse` | Story | Story output with narrative |
| `StoryExport` | Story | Export format selection |
| `TimelineQuery` | Timeline | Date range and filter params |
| `MemoryStats` | Insights | Aggregated memory statistics |
| `TrendData` | Insights | Time-series data point |
| `MemoryTrends` | Insights | Weekly trends (memories per week, mood) |
| `WordCloudData` | Insights | Word frequency pair |
| `Achievement` | Insights | Badge/achievement with progress |
| `InsightsResponse` | Insights | Full insights dashboard |
| `JobStatusResponse` | Jobs | Async job tracking |
| `ErrorResponse` | General | Standard error format |

### Validation Rules

- **Username**: 3–255 chars, alphanumeric + underscore/hyphen only
- **Email**: Valid email format (Pydantic `EmailStr`)
- **Password**: Minimum 8 characters
- **Entity type**: Must be one of `person`, `place`, `date`, `event`, `concept`
- **Input type**: Must be one of `voice`, `text`, `form`
- **Story type**: Must be one of `chronological`, `thematic`, `curated`, `digest`
- **Importance level**: 1–10, default 5
- **Search limit**: 1–100, default 20

## ORM ↔ Schema Mapping

The `MemoryResponse` schema uses `from_attributes = True` to convert SQLAlchemy ORM objects to API responses. In the capture endpoint ([`app/routes/memories.py`](../app/routes/memories.py)), the conversion is done manually field-by-field. When the agent pipeline is implemented, `StructuredMemory` will be serialized into the ORM's `structured_content` JSONB column and deserialized back on read.