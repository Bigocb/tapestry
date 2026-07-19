---
type: Project Overview
title: MEMIND Quickstart
description: Entry point for the MEMIND wiki. MEMIND is a multi-user AI-powered memory capture and enhancement platform built with FastAPI, PostgreSQL/pgvector, and a pipeline of specialized AI agents.
tags: [memind, quickstart, overview]
---

# MEMIND Quickstart

**MEMIND** is a multi-user AI-powered memory capture and enhancement platform. Users record voice memos, text, or form submissions, and specialized AI agents parse, refine, enrich, and help users build narratives from their memories.

## What MEMIND Does

1. **Captures memories** via voice, text, or form inputs (synchronous, instant feedback)
2. **Refines raw captures** through a pipeline of AI agents (asynchronous background processing)
3. **Enriches memories** with extracted entities, related memories via RAG, tags, and context
4. **Provides hybrid search** (full-text + semantic + structured filters)
5. **Generates narratives** by stitching memories into stories
6. **Displays timelines** for chronological browsing
7. **Offers insights and gamification** for reflection and engagement

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI |
| Data Models | Pydantic v2 |
| Database | PostgreSQL 15+ with pgvector (SQLite for tests) |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Async | SQLAlchemy async sessions |
| LLM | Ollama Cloud API (primary), Claude Opus (fallback for stories) |
| Voice | Whisper via Ollama |
| Frontend | React/Next.js (planned, not yet in repo) |
| Deployment | Render |

## Current Implementation Status

The codebase is in **early Phase 2**. The following are implemented and tested:

- FastAPI application structure with health check and CORS
- JWT authentication (register, login, token refresh) with 20 passing tests
- Memory capture endpoint (`POST /api/memories/capture`)
- Pydantic schemas for all planned domains (users, memories, entities, search, stories, insights)
- SQLAlchemy ORM models for users, memories, entities, stories, and job_status
- Async database layer with cross-DB compatibility (PostgreSQL + SQLite)

The following are **planned but not yet implemented**:

- AI agent pipeline (capture, refinement, enrichment, search, story agents)
- Search, story, timeline, and insights API routes
- Voice transcription via Whisper
- Vector embedding and semantic search via pgvector
- Frontend (React/Next.js)

## Wiki Navigation

- [Architecture](architecture.md) — FastAPI app structure, routing, middleware, tech stack decisions
- [Authentication](auth.md) — JWT flow, password hashing, token refresh, route protection
- [Data Models](data-models.md) — Pydantic schemas, SQLAlchemy ORM, cross-DB compatibility, processing state machine
- [Memory Pipeline](memory-pipeline.md) — Capture endpoint, processing states, planned agent pipeline, enrichment ideas
- [Testing](testing.md) — Test setup, SQLite in-memory strategy, known Postgres-specific test gaps

## Repository Structure

```
app/
  main.py              # FastAPI entry point, CORS, lifespan, route inclusion
  security.py           # JWT creation/verification, password hashing
  dependencies.py       # get_current_user dependency for protected routes
  db/
    connection.py       # Async engine + session factory
    models.py           # SQLAlchemy ORM (User, Memory, Entity, Story, JobStatus)
  models/
    schemas.py          # Pydantic v2 schemas (all domains)
  routes/
    auth.py             # /api/auth/register, login, refresh
    memories.py         # /api/memories/capture
  agents/
    __init__.py         # (empty — agents not yet implemented)
tests/
  conftest.py           # SQLite in-memory DB fixture
  test_auth.py          # 20 auth tests
  test_memory_capture.py # Memory capture tests
  test_fastapi_app.py   # App health/CORS tests
  test_pydantic_models.py # Schema validation tests
  test_db_setup.py      # Database schema + pgvector tests
```

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (defaults to local Postgres) |
| `JWT_SECRET_KEY` | Secret for JWT signing (defaults to dev key) |
| `OLLAMA_API_KEY` | Ollama Cloud API key |
| `OLLAMA_BASE_URL` | Ollama API base URL |
| `CLAUDE_API_KEY` | Anthropic Claude fallback key |
| `ENVIRONMENT` | `development` or `production` |

See `.env.example` for the full template.

## Backlog

| Area | Source | Reason |
|------|--------|--------|
| Search API routes | `app/models/schemas.py` (SearchQuery, SearchResponse) | Only schemas defined; no route code yet |
| Story generation routes | `app/models/schemas.py` (StoryGenerate, StoryResponse) | Only schemas defined; no route code yet |
| Timeline & insights routes | `app/models/schemas.py` (TimelineQuery, InsightsResponse) | Only schemas defined; no route code yet |
| AI agents | `app/agents/__init__.py` | Empty module; agents planned in ISSUES.md Issues 5-9 |
| Frontend | `ARCHITECTURE.md` | React/Next.js planned; no code in repo |
| Deployment config | `DB_SETUP.md` | Render deployment described but no config files present |