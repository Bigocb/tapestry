---
type: Workflow
title: MEMIND Memory Pipeline
description: How memories flow through capture, refinement, enrichment, and story generation in MEMIND, including the processing state machine and planned agent architecture.
tags: [memind, pipeline, memory, agents, rag, enrichment]
---

# Memory Pipeline

The memory pipeline is MEMIND's core workflow: from raw user input to a fully enriched, searchable memory. The pipeline has both a **synchronous path** (instant feedback) and an **asynchronous path** (background agent processing).

## Current State

Only the **capture endpoint** is implemented. The asynchronous agent pipeline is planned but not yet built. The `app/agents/` package exists but is empty.

## Processing State Machine

Each memory transitions through these states:

```
raw → capturing → refined → enriching → enriched → ready
```

| State | Meaning | Who sets it |
|-------|---------|-------------|
| `raw` | Just captured, no processing yet | Capture endpoint |
| `capturing` | Capture Agent is structuring the raw input | Capture Agent (planned) |
| `refined` | Structured content is populated | Refinement Agent (planned) |
| `enriching` | Enrichment Agent is adding context | Enrichment Agent (planned) |
| `enriched` | Tags, importance, related memories added | Enrichment Agent (planned) |
| `ready` | Fully processed, searchable | Background job completion (planned) |

Currently, the capture endpoint creates memories in the `raw` state and no further transitions happen.

## Capture Flow (Implemented)

`POST /api/memories/capture` — [`app/routes/memories.py`](../app/routes/memories.py)

1. Requires authenticated user via [Authentication](auth.md) dependency
2. Accepts `MemoryCapture` schema: `raw_input` (text) and `input_type` (`voice`, `text`, or `form`)
3. Creates a `Memory` record with `processing_state="raw"`, empty tags and related_memory_ids
4. Returns `MemoryResponse` immediately — user sees their raw capture right away
5. Planned: schedule background refinement job (not yet implemented)

The synchronous design ensures no user-facing latency regardless of how long background processing takes.

## Planned Agent Pipeline

### Capture Agent (Synchronous, ~1s)

- **Input**: Raw text (transcribed voice, pasted text, or form data)
- **Output**: `StructuredMemory` with title, summary, entities, mood, initial_tags
- **Trigger**: Immediately after capture
- **Status**: Not implemented. The PRD specifies this should run as part of the capture response.

### Refinement Agent (Async, ~2–3s)

- **Input**: Structured memory + similar past memories from database
- **Output**: Refined memory with resolved references, normalized entities
- **Example**: "that meeting" → "Q3 Planning meeting on July 15"
- **Trigger**: Scheduled after capture completes
- **Status**: Not implemented

### Enrichment Agent (Async, ~3–5s)

- **Input**: Refined memory + vector embedding
- **Process**:
  1. Generate embedding via Ollama embeddings model
  2. Query pgvector for top-5 semantically similar memories (RAG)
  3. Suggest tags, importance level, thematic connections
- **Output**: Tags, related_memory_ids, importance_level, connection notes
- **Trigger**: Scheduled after refinement completes
- **Status**: Not implemented

### Search Agent (On-Demand)

- **Input**: Natural language user query
- **Output**: Structured `SearchQuery` object (text terms, semantic query, filters)
- **Example**: "Tell me about my manager chats in Q1" → `{text: "manager", filters: {date_range: Q1}}`
- **Status**: Not implemented

### Story Agent (On-Demand)

- **Input**: Selected memories + story_type + optional custom prompt
- **Output**: Markdown narrative
- **Story types**: chronological, thematic, curated, digest
- **Fallback**: Claude Opus if Ollama quality is insufficient
- **Status**: Not implemented

## Job Tracking

The `JobStatus` ORM model ([`app/db/models.py`](../app/db/models.py)) tracks background processing:

| Field | Values |
|-------|--------|
| task_type | `refinement`, `enrichment`, `story` |
| status | `pending`, `running`, `completed`, `failed` |
| progress | 0.0–1.0 |

This table is defined but not yet used by any route or agent code.

## Enrichment Ideas

[`ENRICHMENT_IDEAS.md`](../ENRICHMENT_IDEAS.md) documents brainstormed enrichment sources beyond the core pipeline:

- **Location**: GPS, reverse geocoding, weather at time of memory
- **Temporal**: Calendar integration, holidays, moon phases
- **News**: What was happening in the world when the memory was created
- **Music/Media**: Spotify listening history, movie releases
- **Health**: Fitness tracker data, sleep quality, mood correlations
- **Social**: Entity frequency, relationship patterns, contact patterns

These are exploratory ideas documented for future consideration, not currently implemented or planned in any issue.

## Key Source Files

| File | Role |
|------|------|
| `app/routes/memories.py` | Capture endpoint — the only implemented pipeline step |
| `app/models/schemas.py` | `MemoryCapture`, `MemoryResponse`, `MemoryUpdate`, `StructuredMemory` |
| `app/db/models.py` | `Memory` and `JobStatus` ORM models |
| `app/agents/__init__.py` | Empty — agents will go here |
| `ENRICHMENT_IDEAS.md` | Brainstormed enrichment data sources |
| `ISSUES.md` | Issues 5–9 define the agent pipeline |
| `ARCHITECTURE.md` | Full pipeline specification in the PRD section |