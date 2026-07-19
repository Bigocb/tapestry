---
type: Architecture
title: MEMIND Architecture
description: FastAPI application structure, routing, middleware, tech stack decisions, and how the components fit together.
tags: [memind, architecture, fastapi, routing, middleware]
---

# MEMIND Architecture

## Application Entry Point

The application starts in [`app/main.py`](../app/main.py), which creates a `FastAPI` instance with:

- **Title**: `MEMIND API`
- **Version**: `0.1.0`
- **OpenAPI tags**: health, auth, memories, search, stories, timeline, insights
- **Lifespan**: Simple startup/shutdown logging via `asynccontextmanager`
- **CORS**: Allows `localhost:3000` and `localhost:8000` origins, with credentials and all methods/headers

The app is runnable via `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.

## Route Registration

Routes are included with the `/api` prefix:

```python
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(memories.router, prefix="/api", tags=["memories"])
```

Currently implemented routes:

| Prefix | File | Endpoints |
|--------|------|-----------|
| `/api/auth` | [`app/routes/auth.py`](../app/routes/auth.py) | register, login, refresh |
| `/api/memories` | [`app/routes/memories.py`](../app/routes/memories.py) | capture |

Planned but not yet implemented: search, stories, timeline, insights.

## Middleware Stack

- **CORS** (`CORSMiddleware`): Allows frontend development on localhost:3000 to communicate with the API on localhost:8000. Credentials and all methods/headers are enabled.

## Dependency Injection

MEMIND uses FastAPI's `Depends` pattern for:

- **Database sessions**: `get_db()` in [`app/db/connection.py`](../app/db/connection.py) yields an async SQLAlchemy session
- **Authentication**: `get_current_user()` in [`app/dependencies.py`](../app/dependencies.py) extracts the JWT bearer token, decodes it, and loads the user from the database — see [Authentication](auth.md) for details

## Tech Stack Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Web framework | FastAPI | Async support, OpenAPI docs, dependency injection |
| Data validation | Pydantic v2 | Type-safe schemas, validation, serialization |
| Database | PostgreSQL 15+ with pgvector | Structured data + vector embeddings in one database |
| ORM | SQLAlchemy async | Async I/O, cross-DB compatibility for tests |
| Auth | JWT (python-jose) + bcrypt (passlib) | Stateless auth, industry-standard hashing |
| LLM | Ollama Cloud API (primary) | Open-source models, low latency for capture/refine |
| LLM fallback | Claude Opus (Anthropic) | Higher-quality story generation |
| Voice | Whisper via Ollama | Speech-to-text for voice captures |
| Deployment | Render | Managed PostgreSQL + FastAPI hosting |

### Why pgvector over Pinecone/Weaviate

MEMIND intentionally uses pgvector within PostgreSQL rather than a dedicated vector database. This keeps infrastructure simple — one database for structured data, full-text search, and vector similarity — while reducing operational complexity and cost. The trade-off is that pgvector is less feature-rich for vector search at massive scale, which is acceptable for MEMIND's current scope.

## Planned Agent Pipeline

The agent pipeline is described in [Memory Pipeline](memory-pipeline.md) but not yet implemented. The architecture calls for five specialized agents:

1. **Capture Agent** — synchronous, structures raw input
2. **Refinement Agent** — async, resolves ambiguities
3. **Enrichment Agent** — async, RAG + tags + importance
4. **Search Agent** — on-demand, natural language to structured query
5. **Story Agent** — on-demand, Ollama-first with Claude fallback

Each agent is intended to run as a background job tracked in the `job_status` table. The `app/agents/` package exists but is currently empty.

## Source Map

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, CORS, lifespan, route inclusion |
| `app/dependencies.py` | `get_current_user` dependency |
| `app/security.py` | JWT creation/verification, password hashing |
| `app/routes/auth.py` | Auth endpoints (register, login, refresh) |
| `app/routes/memories.py` | Memory capture endpoint |
| `app/db/connection.py` | Async engine and session factory |
| `app/db/models.py` | SQLAlchemy ORM models |
| `app/models/schemas.py` | Pydantic v2 schemas for all domains |