---
type: Reference
title: Tapestry Testing
description: Test strategy, fixtures, patterns, and known limitations for Tapestry, including SQLite vs PostgreSQL compatibility notes.
tags: [tapestry, testing, pytest, sqlite, postgresql]
---

# Testing

Tapestry uses **pytest** with **pytest-asyncio**. Tests run against an in-memory
SQLite database, so the suite needs no running PostgreSQL and takes about three
minutes end to end.

## Running Tests

```bash
pytest -q                      # whole suite
pytest tests/test_entity_model.py -v
```

Expected result: **365 tests collected, all passing, 1 skipped** (the pgvector
test, which is PostgreSQL-only). The suite runs in roughly three minutes.

## Configuration

[`pytest.ini`](../pytest.ini):

- `asyncio_mode = auto`
- `testpaths = tests`
- `pythonpath = .`

[`tests/conftest.py`](../tests/conftest.py) sets `DATABASE_URL` to SQLite
in-memory before imports, and — importantly — **tracks every async engine**
created during the session and disposes it at teardown.

> Without that disposal the suite *passes* but never exits: `aiosqlite` runs each
> connection on a non-daemon worker thread, so the interpreter waits on it at
> shutdown. If pytest ever appears to hang after printing results, that is why.

## Test Files

| Area | Files |
|------|-------|
| App & models | `test_fastapi_app.py`, `test_pydantic_models.py` (36) |
| Auth & session | `test_auth.py` (26) |
| Memory lifecycle | `test_memory_capture.py`, `test_memory_retrieval.py`, `test_memory_update.py`, `test_memory_delete.py` |
| Agents | `test_capture_agent.py` (20), `test_refinement_agent.py`, `test_enrichment_agent.py`, `test_story_agent.py`, `test_search_agent.py`, `test_embeddings.py` |
| Dates | `test_fuzzy_dates.py` (24) |
| Entities | `test_entity_model.py` (22), `test_entity_write_path.py`, `test_entity_read.py`, `test_entity_merge.py`, `test_entity_hierarchy.py` |
| Related memories | `test_related_memories.py` (16) |
| Privacy & review | `test_privacy_lock.py`, `test_review_queue.py` |
| Search, stories, insights, timeline | `test_hybrid_search.py`, `test_search_natural.py`, `test_stories.py`, `test_insights.py`, `test_timeline.py` |
| Jobs & wiki | `test_scheduler.py`, `test_wiki_routes.py`, `test_db_setup.py` |

## Fixtures

Each test module builds its own in-memory database and a `TestClient` with
`get_db` overridden. Common shape:

```python
@pytest.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = sessionmaker(engine, class_=AsyncSession,
                                expire_on_commit=False, autoflush=False)
    async with SessionLocal() as session:
        yield session
```

Tests needing a token either register/login through the API or mint one with
`create_access_token`.

For tests that exercise the background pipeline, the scheduler's session factory
must be pointed at the test database:

```python
from app.jobs import scheduler as scheduler_module
scheduler_module.BackgroundSessionLocal = factory
```

## SQLite vs PostgreSQL

`DBJSON` and `GUID` type decorators bridge the dialects. PostgreSQL-only pieces
(`GIN` tag index, `ivfflat`, `information_schema` queries) are declared but do
not work on SQLite, which is why `test_db_setup.py` is largely skipped.

**Id typing**: model defaults return `UUID` objects, never `str`. Mixing the two
makes SQLAlchemy's flush ordering compare `UUID < str` and raise. There is a
regression test guarding this (`TestIdTypeConsistency`).

## Patterns Worth Reusing

**Prove a guard is real.** Several privacy and filtering tests were verified by
temporarily disabling the filter and confirming the test fails. A test that
passes either way is not protecting anything.

**Assert on observable behaviour.** Entity tests check mention counts and which
names resolve, not internal call shapes.

**Seed through the service.** Entity tests call `sync_memory_entities` rather
than inserting rows directly, so they exercise the same path production uses.

## Known Limitations

- **Agent output is not asserted against a live model.** Agents are stubbed or
  monkeypatched, so prompts and parsing are tested but real model quality is not
- **PostgreSQL path is unexercised.** pgvector similarity and `tsquery` search
  are not covered because the suite runs on SQLite
- **No end-to-end browser tests.** The frontend has typecheck and lint only
- **Voice transcription** is tested with a stubbed model, not real audio; accuracy is not asserted
- **Concurrency** (two jobs racing the same memory) is designed against but not
  load-tested
