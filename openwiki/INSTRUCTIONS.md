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
- Authentication flow (JWT, password hashing via `passlib`/`bcrypt`).
- Database layer using SQLAlchemy async with SQLite in tests and PostgreSQL/pgvector for production.
- Memory capture pipeline: text, voice, form inputs, async refinement/enrichment, RAG, search, and story generation.
- Test coverage and known test limitations (some DB tests use Postgres-specific syntax that fails on SQLite).

## What to avoid

- Do not invent or assume deployment URLs, credentials, or API keys.
- Do not claim the project uses vector databases like Pinecone or Weaviate when the architecture explicitly chooses pgvector in PostgreSQL.
- Do not document features as complete if the code only contains stubs or TODOs. Mark those as deferred.

## Update cadence

Run on each meaningful commit, or daily for active development. Keep docs in `openwiki/` up to date with the actual file contents.
