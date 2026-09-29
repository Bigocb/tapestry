---
type: Architecture
title: MEMIND Architecture
description: FastAPI application structure, routing, middleware, dependency injection, and how the components fit together.
tags: [memind, architecture, fastapi, routing, middleware]
---

# MEMIND Architecture

## Application Entry Point

[`app/main.py`](../app/main.py) creates the `FastAPI` instance and owns startup:

- Title `MEMIND API`, version `0.1.0`
- OpenAPI tags: health, auth, memories, search, stories, timeline, insights,
  review, entities, wiki
- **Lifespan** does real work: it drops the legacy `entities` table if present,
  runs `Base.metadata.create_all`, applies additive migrations and one-time
  backfills, then starts the APScheduler instance
- **CORS** allows `localhost:3000` and `localhost:8000`

Run with `uvicorn app.main:app --port 8000`.

## Routers

All routers are included under `/api`:

| Prefix | File | Highlights |
|--------|------|------------|
| `/api/auth` | `routes/auth.py` | register, login, refresh, `session-config` |
| `/api/memories` | `routes/memories.py` | capture (text/voice/form), list, get, patch, delete, search, `{id}/related` |
| `/api/stories` | `routes/stories.py` | generate, list, get, export |
| `/api/timeline` | `routes/timeline.py` | chronological listing with filters |
| `/api/insights` | `routes/insights.py` | stats, trends, word-cloud, achievements |
| `/api/review` | `routes/review.py` | review queue and count |
| `/api/entities` | `routes/entities.py` | list, counts, detail, merge, undo, merge-suggestions |
| `/api/wiki` | `routes/wiki.py` | OpenWiki viewer |

`/health` and `/health/ollama` live on the app itself.

### Route ordering caveat

In `routes/entities.py`, `GET /entities/{entity_id}` is declared **last**. FastAPI
matches in declaration order, so if it came first it would swallow
`/entities/counts` and `/entities/merge-suggestions` by trying to parse them as
UUIDs. Keep static paths above dynamic ones.

## Middleware Stack

- **CORS** — only middleware. Note that when a handler raises, the error can
  propagate past CORS and the browser reports a network failure instead of the
  status code; the frontend API client compensates by reporting 5xx distinctly.

## Dependency Injection

- **`get_db()`** (`app/db/connection.py`) — yields an async session
- **`get_current_user()`** (`app/dependencies.py`) — decodes the JWT and loads
  the user; all protected routes depend on it, and every query filters by
  `user_id`
- **`get_unlocked_memory_ids()`** (`app/privacy.py`) — parses
  `X-Unlocked-Memory-Ids` so read paths can redact locked memories

## Background Jobs

`app/jobs/scheduler.py` wraps `AsyncIOScheduler`; `app/jobs/worker.py` executes
tracked jobs. Key behaviours:

- Refinement chains into enrichment, each recorded in `job_status`
- When the scheduler is **not** running (e.g. under `TestClient`) the job runs
  inline instead — never both, or the two runs would race on the same row
- User edits are carried on `job_status.overrides` and re-applied after each
  agent stage so reprocessing cannot clobber them
- Failure handler rolls back and re-fetches rows, so it cannot itself crash

## Migrations

There is no migration framework. `main.py` applies **additive** changes idempotently:

1. `_drop_legacy_entity_table()` — the Phase 1 `entities` table had an
   incompatible shape (and 0 rows); it is salvaged into `structured_content`
   then dropped before `create_all`
2. `_has_column` checks add missing columns (`event_date`, `needs_review`,
   `date_precision`, `is_private`, `entities_backfilled`, ...)
3. One-time backfills: recover event dates for undated memories, and populate
   entity tables from legacy JSON (`entities_backfilled` guards this)

Because `create_all` never alters an existing table, a column rename or type
change needs an explicit step here.

## Data Access Conventions

- All ids are `GUID` (UUID objects in Python, adapted per dialect). Model
  defaults yield `uuid.uuid4`, **not** `str(...)` — mixing the two makes
  SQLAlchemy's flush ordering compare `UUID < str` and raise
- Sessions run with `autoflush=False`, so explicit `flush()` is needed where a
  later query must see an earlier in-session change
- JSON columns use `DBJSON` (JSONB on Postgres, JSON on SQLite)
- Datetimes may be naive or aware depending on origin; normalise with
  `app.db.datetime_utils.as_utc` before comparing

## Source Map

| File | Purpose |
|------|---------|
| `app/main.py` | app, lifespan, migrations, router inclusion |
| `app/dependencies.py` | `get_current_user` |
| `app/security.py` | JWT, password hashing, session policy |
| `app/privacy.py` | unlock header, redaction |
| `app/db/models.py` | ORM models |
| `app/db/entities.py` | entity resolution, merging, hierarchy, related memories |
| `app/db/connection.py` | async engine and session factory |
| `app/db/datetime_utils.py` | `as_utc` normalisation |
| `app/models/schemas.py` | Pydantic v2 schemas |
| `app/routes/` | HTTP endpoints |
| `app/agents/` | LLM agents and embeddings |
| `app/jobs/` | scheduler and worker |
| `frontend/` | Next.js app |
