---
type: Workflow
title: MEMIND Memory Pipeline
description: How memories flow from capture through refinement and enrichment, how dates and entities are extracted, and how related memories are derived.
tags: [memind, pipeline, memory, agents, entities, dates]
---

# Memory Pipeline

From raw input to a fully enriched, searchable memory. There is a synchronous
path (instant feedback) and an asynchronous path (background agents).

## Capture Flow

Endpoints: `POST /api/memories/capture/{text,voice,form}` in
[`app/routes/memories.py`](../app/routes/memories.py).

1. Authenticate via `get_current_user`
2. Create the `Memory` row
3. Run the **Capture Agent** (`structure_memory`) synchronously and store the result
4. Sync first-class entities from the structured content
5. Schedule refinement + enrichment via APScheduler
6. Return immediately

Voice captures first go through `_transcribe_audio`, which currently raises
501 — no transcription backend is wired.

## Agents

| Agent | File | Timing | Role |
|-------|------|--------|------|
| Capture | `agents/capture.py` | synchronous | raw text → `StructuredMemory` |
| Refinement | `agents/refinement.py` | async | resolve ambiguities, normalise entities |
| Enrichment | `agents/enrichment.py` | async | tags, importance, connections |
| Embeddings | `agents/embeddings.py` | async | vectors for semantic search |
| Search | `agents/search.py` | on demand | natural language → `SearchQuery` |
| Story | `agents/story.py` | on demand | memories → markdown narrative |

All are Ollama-first. Only the Story agent implements the Claude fallback
(gated on a response-quality check). Every agent falls back to a deterministic
result rather than raising, so the pipeline never stalls on a model failure.

### Date resolution

`capture.resolve_date()` returns a `ResolvedDate` carrying both a representative
date and how precise it actually is. Order matters: **fuzzy periods are checked
first** so "1987 to 1990" is preserved as a range rather than collapsed to 1987.

Handled forms include explicit dates, relative phrases, weekdays, seasons,
holidays, month/year, bare years, decades with early/mid/late qualifiers, and
explicit year ranges.

A fuzzy period is a real answer, not a missing one, so it is **not** sent to the
review queue.

### Entity extraction

`capture` asks the model for `person` / `place` / `organization` entities, with
`metadata.relation` for people (e.g. "wife") and `metadata.parent` for places
contained in other places.

`sync_memory_entities()` is the single entry point for every stage that writes
`structured_content`. Because reprocessing rewrites content wholesale, it
**replaces** a memory's mentions rather than only adding: entities no longer
present are detached and counts are recomputed. Entities themselves are never
deleted — their `mention_count` simply drops.

## Processing States

```
raw → capturing → refined → enriched
```

`JobStatus` records each stage. Failures set `<stage>_failed` without breaking
the capture response. When the scheduler is not running (tests), jobs execute
inline — never both, or two concurrent runs would race on the same memory.

## Editing and Reprocessing

`PATCH /api/memories/{id}`:

- Changing `raw_input` requeues refinement + enrichment, because everything
  derived from the text is now stale
- Editing only metadata does **not** requeue
- Any field set in the same request is stored as an `override` on the job and
  re-applied after each agent stage, so your corrections survive the rerun

## Review Queue

A memory with no time information cannot be placed on the timeline, so it is
flagged `needs_review` with reason `missing_date` and listed at `/review`.
Setting a date, or any fuzzy period label, clears the flag.

## Related Memories

Related memories are **derived on read** (`find_related_memories`), not stored:
memories sharing first-class entities, ranked by number of shared entities then
recency, returned with the shared entity names so the relationship is
explainable.

This replaced the stored `related_memory_ids`, which stayed empty because the
enrichment agent depended on embeddings that older memories never received.
Derived relations work retroactively and cannot go stale.

## Privacy

A private memory is redacted in every response unless its id appears in the
`X-Unlocked-Memory-Ids` header. The unlock is session-scoped and never
persisted, so a refresh re-locks. Locked memories are excluded from search
scoring, insights aggregates, entity lists/counts, and related-memory results.

## Further Reading

- [`docs/ENTITY_MODEL.md`](../docs/ENTITY_MODEL.md) — entity model design
- [`ENRICHMENT_IDEAS.md`](../ENRICHMENT_IDEAS.md) — brainstormed enrichment sources
