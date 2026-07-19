---
type: Documentation Index
title: "OpenWiki"
description: "Files and subdirectories in OpenWiki."
---

# Files

- [MEMIND Architecture](architecture.md) - FastAPI application structure, routing, middleware, tech stack decisions, and how the components fit together.
- [MEMIND Authentication](auth.md) - JWT authentication flow, password hashing, token refresh, and route protection in MEMIND.
- [MEMIND Data Models](data-models.md) - Pydantic schemas and SQLAlchemy ORM models for users, memories, entities, stories, search, and insights in MEMIND, including cross-database compatibility details.
- [MEMIND Memory Pipeline](memory-pipeline.md) - How memories flow through capture, refinement, enrichment, and story generation in MEMIND, including the processing state machine and planned agent architecture.
- [MEMIND Quickstart](quickstart.md) - Entry point for the MEMIND wiki. MEMIND is a multi-user AI-powered memory capture and enhancement platform built with FastAPI, PostgreSQL/pgvector, and a pipeline of specialized AI agents.
- [MEMIND Testing](testing.md) - Test strategy, fixtures, known limitations, and how to run tests for the MEMIND platform, including SQLite vs PostgreSQL compatibility notes.
