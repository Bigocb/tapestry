---
type: Project Overview
title: MEMIND Quickstart
description: Entry point for the MEMIND wiki. MEMIND is a multi-user AI-powered memory capture and enhancement platform built with FastAPI, SQLAlchemy async, a pipeline of specialized AI agents, and a Next.js frontend.
tags: [memind, quickstart, overview]
---

# MEMIND Quickstart

**MEMIND** is a multi-user AI-powered memory capture and enhancement platform.
Users record voice memos, text, or form submissions; specialized AI agents
parse, refine and enrich them; and the app surfaces them as a timeline, a
searchable corpus, browsable people and places, and generated narratives.

## What MEMIND Does

1. **Captures memories** via text, voice or form input (synchronous, instant feedback)
2. **Refines and enriches** them through a background agent pipeline
3. **Extracts first-class entities** (people, places, organizations) that can be browsed, merged and linked
4. **Derives related memories** from shared entities
5. **Provides hybrid search** (full-text + semantic + structured filters)
6. **Generates narratives** by stitching memories into stories
7. **Builds a timeline** of memories placed by when the event happened
8. **Offers insights, achievements and a review queue**

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy async |
| Data Models | Pydantic v2 |
| Database | SQLite for local dev, PostgreSQL + pgvector for production |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Async jobs | APScheduler (in-memory) |
| LLM | Ollama Cloud API (`ollama.com/v1`); Claude fallback for stories |
| Frontend | Next.js (App Router) + React + Tailwind, in `frontend/` |
| Deployment | Render (not yet configured) |

## Capabilities

**Memory processing**

- Capture from text, voice (audio upload) or structured form
- Background pipeline: capture → refinement → enrichment, tracked in `job_status`
- Editing the source text requeues the pipeline; manual edits are preserved as
  overrides so reprocessing cannot clobber them
- Undated memories go to a **review queue** rather than being hidden

**Dates**

- Extracted from text (explicit, relative, seasonal, holiday, decade, range)
- **Fuzzy periods** are first-class: "the 80s", "middle school 1987-1990",
  "sometime in middle school" are preserved as periods, not faked into an
  exact date (`date_precision`, `event_date_end`, `date_label`)
- The timeline excludes memories with no time information; they belong to review

**Entities (people, places, organizations)**

- First-class: `entities`, `entity_aliases`, `memory_entities`, `entity_merges`
- Only *exact* normalized names auto-link; fuzzy matches are suggested for
  confirmation, and merges are reversible with an audit trail
- Places support containment ("Bluebird Cafe" inside "Denver"), inferred by the
  capture agent and cycle-checked
- Browse at `/people` and `/places`; detail pages show aliases and mentions

**Privacy**

- Per-memory **privacy lock**: content is withheld from every API response until
  unlocked for the session via `X-Unlocked-Memory-Ids`
- Derived privacy: an entity is visible only if a non-locked memory mentions it
- **Session inactivity timeout** with a warning countdown (configurable)

**Other**

- Hybrid search, natural-language search
- Story generation (4 types) with markdown/txt/json export
- Timeline, insights (stats, trends, word cloud, achievements)
- Wiki viewer for OpenWiki docs at `/api/wiki`
- Voice, text and form capture UI

## Running Locally

```bash
# Backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # includes apscheduler
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# Frontend
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Tables are created on startup and additive migrations run automatically. A
backup of the local SQLite database is advisable before schema changes.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Database URL (defaults to `sqlite+aiosqlite:///./memind.db`) |
| `OLLAMA_API_BASE` | Ollama API base (default `https://ollama.com/v1`) |
| `OLLAMA_MODEL` | Chat model for agents |
| `OLLAMA_API_KEY` | Ollama Cloud API key |
| `JWT_SECRET_KEY` | JWT signing secret |
| `SESSION_IDLE_MINUTES` | Inactivity timeout (default 15) |
| `SESSION_IDLE_WARNING_SECONDS` | Warning countdown (default 60) |

See `.env.example` for the template.

## Wiki Navigation

- [Architecture](architecture.md) — app structure, routing, dependency injection
- [Authentication](auth.md) — JWT flow and session handling
- [Data Models](data-models.md) — ORM models and Pydantic schemas
- [Memory Pipeline](memory-pipeline.md) — capture through enrichment
- [Testing](testing.md) — how the suite is structured and run

Related design notes outside this wiki:

- `docs/ENTITY_MODEL.md` — the entity model in depth
- `ISSUES.md` — the original phase plan and status
- `ARCHITECTURE.md`, `PRD.md` — original design documents

## Repository Structure

```
app/
  main.py              FastAPI entry point, lifespan, migrations, routers
  security.py          JWT + password hashing, session policy config
  dependencies.py      get_current_user
  privacy.py           unlock-header dependency and redaction rules
  db/
    connection.py      async engine + session factory
    models.py          ORM: User, Memory, Entity, EntityAlias, MemoryEntity,
                       EntityMerge, Story, JobStatus
    entities.py        entity resolution, merging, hierarchy, related memories
    datetime_utils.py  naive/aware normalisation
  models/schemas.py    Pydantic v2 schemas
  routes/              auth, memories, stories, timeline, insights, review,
                       entities, wiki
  agents/              capture, refinement, enrichment, embeddings, search, story
  jobs/                scheduler + worker
frontend/
  app/                 Next.js routes (capture, search, timeline, stories,
                       insights, review, people, places, entities, memories)
  components/          UI components
  lib/                 api client, auth, privacy, date formatting, session
tests/                 ~365 tests across 25+ files
docs/ENTITY_MODEL.md   entity model design
openwiki/              this wiki
```

## Known Gaps

| Area | Status |
|------|--------|
| Voice transcription | Endpoint accepts audio but `_transcribe_audio` returns 501; no backend wired |
| pgvector | Embeddings stored as JSON strings; similarity computed in Python, not via pgvector ANN |
| Deployment | No `render.yaml`/`Dockerfile`; Render described in `DB_SETUP.md` only |
| Attachments | Not started (images/video were requested) |
| Scheduler | In-memory job store; no persistence or retry policy |
