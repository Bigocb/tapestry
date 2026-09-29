---
type: Instructions
title: MEMIND OpenWiki Instructions
description: Agent instructions for documenting the MEMIND project.
---

# MEMIND OpenWiki Instructions

This repository contains **MEMIND**, a multi-user AI-powered memory capture and enhancement platform.

## Project focus

Document the following aspects accurately and concisely:

- FastAPI application structure (`app/main.py`, `app/routes/`, `app/db/`, `app/models/`).
- Pydantic data models for users, memories, entities, search, stories, and insights.
- Authentication flow (JWT, password hashing via `passlib`/`bcrypt`) and the
  client-side session inactivity timeout.
- Database layer using SQLAlchemy async with SQLite in tests and local dev,
  PostgreSQL/pgvector for production. Note the `GUID`/`DBJSON` type decorators
  and the rule that ids are `UUID` objects, never `str`.
- Memory capture pipeline: text, voice, form inputs, async refinement/enrichment,
  search, and story generation. Voice transcription is a 501 stub.
- **First-class entities** (people, places, organizations): `entities`,
  `entity_aliases`, `memory_entities`, `entity_merges`. Exact-name auto-linking,
  reversible merges, place containment, and derived related memories. See
  `docs/ENTITY_MODEL.md`.
- **Fuzzy dates**: `date_precision`, `event_date_end`, `date_label` — rough
  periods are preserved, not faked into exact dates.
- **Privacy**: per-memory lock via `X-Unlocked-Memory-Ids`, and the review queue
  for undated memories.
- The Next.js frontend lives in `frontend/`.
- Test coverage and known test limitations (some DB tests use Postgres-specific
  syntax that fails on SQLite). The suite tracks and disposes engines in
  `conftest.py` so pytest can exit.

## What to avoid

- Do not invent or assume deployment URLs, credentials, or API keys.
- Do not claim the project uses vector databases like Pinecone or Weaviate when
  the architecture explicitly chooses pgvector in PostgreSQL.
- Do not document features as complete if the code only contains stubs or TODOs.
  Voice transcription, pgvector similarity, and Render deployment are **not**
  implemented; mark them deferred.
- Do not describe the frontend as "planned" — it exists in `frontend/`.

## Update cadence

Run on each meaningful commit, or daily for active development. Keep docs in
`openwiki/` up to date with the actual file contents.

> This wiki was hand-reconciled on 2026-09-29 after the automated updater had
> gone stale (the configured model `glm-5.1` had been retired by Ollama). The
> workflow now pins `glm-5.2`.

