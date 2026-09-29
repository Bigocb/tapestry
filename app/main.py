"""MEMIND FastAPI application entry point."""

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from sqlalchemy import inspect, text
from datetime import timezone

# Import routes
from app.routes import (
    auth,
    memories,
    stories,
    wiki,
    timeline,
    insights,
    review,
    entities,
    tellings,
)
from app.jobs.scheduler import scheduler
from app.db import Base, engine
from app.agents.capture import _ollama_config, _extract_event_date

import httpx
import json


# A memory that is queued for review but does in fact carry a time signal: an
# exact date, a fuzzy precision (decade/range) or a human label. Used to heal
# rows that were queued before fuzzy periods counted as real answers.
#
# The boolean is a bound parameter on purpose: `needs_review = 1` is accepted
# by SQLite but rejected by Postgres, which refuses boolean-to-integer
# comparison.
MEMORIES_WITH_TIME_SIGNAL = (
    "needs_review = :queued "
    "AND (event_date IS NOT NULL "
    "     OR date_precision IN ('decade', 'range') "
    "     OR date_label IS NOT NULL AND date_label <> '')"
)


def _has_column(conn, table_name: str, column_name: str) -> bool:
    """Check whether a column exists on the given table."""
    columns = [c["name"] for c in inspect(conn).get_columns(table_name)]
    return column_name in columns


def _has_table(conn, table_name: str) -> bool:
    """Check whether a table exists."""
    return table_name in inspect(conn).get_table_names()


async def _drop_legacy_entity_table() -> None:
    """Drop the pre-entity-model ``entities`` table so it can be rebuilt.

    The Phase 1 table had a completely different shape (a bare
    ``memory_id``/``type``/``value`` triple) and was never populated. The
    first-class entity model replaces it with ``entities`` + ``entity_aliases``
    + ``memory_entities``, which CREATE TABLE cannot express as an ALTER.

    This runs *before* ``create_all`` and is safe because the old table holds
    no data; anything found is migrated into ``structured_content`` first.
    """
    async with engine.begin() as conn:
        if not await conn.run_sync(_has_table, "entities"):
            return
        # The legacy table is identified by its `memory_id` column; the new
        # one has no such column.
        if not await conn.run_sync(_has_column, "entities", "memory_id"):
            return

        result = await conn.execute(text("SELECT COUNT(*) FROM entities"))
        legacy_rows = int(result.scalar_one())
        print(f"Found legacy entities table with {legacy_rows} rows; rebuilding.")

        # Preserve anything that was stored: copy values into the owning
        # memory's structured_content so the normal backfill can pick them up.
        if legacy_rows:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, memory_id, type, value, entity_metadata "
                        "FROM entities"
                    )
                )
            ).fetchall()
            for _row_id, memory_id, entity_type, value, metadata in rows:
                memory = (
                    await conn.execute(
                        text("SELECT structured_content FROM memories WHERE id = :i"),
                        {"i": memory_id},
                    )
                ).scalar_one_or_none()
                if memory is None:
                    continue

                try:
                    content = json.loads(memory) if isinstance(memory, str) else memory
                except (TypeError, ValueError):
                    content = {}
                if not isinstance(content, dict):
                    content = {}

                entities = content.get("entities")
                if not isinstance(entities, list):
                    entities = []
                entities.append(
                    {
                        "type": entity_type,
                        "value": value,
                        "metadata": (
                            json.loads(metadata)
                            if isinstance(metadata, str)
                            else metadata
                        ),
                    }
                )
                content["entities"] = entities
                await conn.execute(
                    text("UPDATE memories SET structured_content = :c WHERE id = :i"),
                    {"c": json.dumps(content), "i": memory_id},
                )

        await conn.execute(text("DROP TABLE entities"))
        print("Dropped legacy entities table.")


async def _apply_pending_migrations() -> None:
    """Add any columns that exist in the model but are missing from the DB."""
    async with engine.begin() as conn:
        if not await conn.run_sync(_has_column, "memories", "event_date"):
            await conn.execute(text("ALTER TABLE memories ADD COLUMN event_date TIMESTAMP"))
            print("Added missing event_date column to memories table.")
        if not await conn.run_sync(_has_column, "memories", "needs_review"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN needs_review BOOLEAN DEFAULT FALSE")
            )
            print("Added missing needs_review column to memories table.")
        if not await conn.run_sync(_has_column, "memories", "review_reason"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN review_reason VARCHAR(50)")
            )
            print("Added missing review_reason column to memories table.")
        if not await conn.run_sync(_has_column, "job_status", "overrides"):
            await conn.execute(text("ALTER TABLE job_status ADD COLUMN overrides JSON"))
            print("Added missing overrides column to job_status table.")
        if not await conn.run_sync(_has_column, "memories", "is_private"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN is_private BOOLEAN DEFAULT FALSE")
            )
            print("Added missing is_private column to memories table.")
        if not await conn.run_sync(_has_column, "memories", "date_precision"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN date_precision VARCHAR(20)")
            )
            print("Added missing date_precision column to memories table.")
        if not await conn.run_sync(_has_column, "memories", "event_date_end"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN event_date_end TIMESTAMP")
            )
            print("Added missing event_date_end column to memories table.")
        if not await conn.run_sync(_has_column, "memories", "date_label"):
            await conn.execute(
                text("ALTER TABLE memories ADD COLUMN date_label VARCHAR(120)")
            )
            print("Added missing date_label column to memories table.")

        # Backfill: memories captured before the review queue existed that have
        # no event date would otherwise be invisible -- excluded from the
        # timeline but never flagged. Park them in the queue instead, trying to
        # recover a date from the raw text first.
        result = await conn.execute(
            text(
                "SELECT id, raw_input FROM memories "
                "WHERE event_date IS NULL AND needs_review = :flagged"
            ),
            {"flagged": False},
        )
        rows = result.fetchall()
        recovered = 0
        flagged = 0
        for memory_id, raw_input in rows:
            parsed = _extract_event_date(raw_input or "")
            if parsed is not None:
                # Store naive UTC so these rows match ORM-written timestamps
                # (SQLite drops tzinfo anyway). Read paths normalise regardless.
                stored = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                await conn.execute(
                    text("UPDATE memories SET event_date = :d WHERE id = :i"),
                    {"d": stored, "i": memory_id},
                )
                recovered += 1
            else:
                await conn.execute(
                    text(
                        "UPDATE memories SET needs_review = :r, review_reason = :reason "
                        "WHERE id = :i"
                    ),
                    {"r": True, "reason": "missing_date", "i": memory_id},
                )
                flagged += 1
        if recovered or flagged:
            print(
                f"Backfilled undated memories: {recovered} dated, {flagged} queued for review."
            )

        # Reconcile review flags: memories processed before fuzzy periods were
        # treated as real answers can carry needs_review even though they have
        # a label, a decade or a range. Only a PATCH re-evaluated the flag, so
        # reviewed-and-set memories silently stayed in the queue. Heal them.
        reconcile = await conn.execute(
            text(f"SELECT COUNT(*) FROM memories WHERE {MEMORIES_WITH_TIME_SIGNAL}"),
            {"queued": True},
        )
        stale = int(reconcile.scalar_one())
        if stale:
            await conn.execute(
                text(
                    "UPDATE memories SET needs_review = :clear, review_reason = NULL "
                    f"WHERE {MEMORIES_WITH_TIME_SIGNAL}"
                ),
                {"clear": False, "queued": True},
            )
            print(
                f"Reconciled review flags: {stale} memories with a time signal "
                "were still queued; cleared."
            )

    # Backfill first-class entities from the JSON still stored in
    # structured_content, then record that it has been done.
    async with engine.begin() as conn:
        if not await conn.run_sync(_has_column, "memories", "entities_backfilled"):
            await conn.execute(
                text(
                    "ALTER TABLE memories ADD COLUMN entities_backfilled "
                    "BOOLEAN DEFAULT FALSE"
                )
            )
            print("Added missing entities_backfilled column to memories table.")
    await _backfill_entities()
    await _backfill_fuzzy_metadata()


async def _backfill_fuzzy_metadata() -> None:
    """Re-derive date precision/label for memories captured before fuzzy dates.

    Memories processed by the early pipeline could carry an event_date with no
    precision or label, so "the 80s" ended up as a bare 1980-01-01 that the
    timeline cannot group. Re-resolve the raw text for those rows and backfill
    precision, range end and label where the resolver finds something fuzzy.
    Only fills blanks -- never overwrites an explicit value.
    """
    from app.agents.capture import resolve_date
    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        pending = (
            await session.execute(
                text(
                    "SELECT id, raw_input FROM memories "
                    "WHERE event_date IS NOT NULL "
                    "AND (date_precision IS NULL OR date_precision = '') "
                    "AND (date_label IS NULL OR date_label = '')"
                )
            )
        ).fetchall()

        if not pending:
            return

        updated = 0
        for memory_id, raw_input in pending:
            # Never touch a precision the user set deliberately; only fill
            # rows that predate fuzzy metadata entirely.
            resolved = resolve_date(raw_input or "")
            # Only fuzzy answers improve a bare exact-date row; a plain
            # resolved date that matches what is already stored adds nothing.
            if resolved.precision not in ("decade", "range"):
                continue
            if not resolved.event_date:
                continue

            if resolved.label:
                label = resolved.label
            elif resolved.precision == "decade":
                label = f"{resolved.event_date.year}s"
            else:
                label = f"{resolved.event_date.year}"
                if resolved.event_date_end:
                    label += f"-{resolved.event_date_end.year}"

            await session.execute(
                text(
                    "UPDATE memories SET date_precision = :p, "
                    "event_date_end = :e, date_label = :l WHERE id = :i"
                ),
                {
                    "p": resolved.precision,
                    "e": (
                        resolved.event_date_end.astimezone(timezone.utc).replace(
                            tzinfo=None
                        )
                        if resolved.event_date_end
                        else None
                    ),
                    "l": label[:120] if label else None,
                    "i": memory_id,
                },
            )
            updated += 1

        await session.commit()
        if updated:
            print(
                f"Backfilled fuzzy date metadata for {updated} memories "
                "(decade/range precision and labels)."
            )


async def _backfill_entities() -> None:
    """Populate entity tables from legacy structured_content JSON.

    Runs once per memory (guarded by ``memories.entities_backfilled``), using
    the same matching rules as live capture so aliases collapse consistently.
    """
    from app.db.entities import apply_mentions
    from app.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        pending = (
            await session.execute(
                text(
                    # `COALESCE(boolean, 0)` is a SQLite-ism that Postgres
                    # refuses; NULL covers rows predating the column.
                    "SELECT id, user_id, structured_content FROM memories "
                    "WHERE entities_backfilled IS NULL "
                    "   OR entities_backfilled = :not_done"
                ),
                {"not_done": False},
            )
        ).fetchall()

        if not pending:
            return

        created = 0
        for memory_id, user_id, raw_content in pending:
            try:
                content = (
                    json.loads(raw_content)
                    if isinstance(raw_content, str)
                    else raw_content
                )
            except (TypeError, ValueError):
                content = {}
            if not isinstance(content, dict):
                content = {}

            mentions = []
            for item in content.get("entities") or []:
                if not isinstance(item, dict):
                    continue
                kind = item.get("type")
                value = item.get("value")
                if kind not in ("person", "place", "organization") or not value:
                    continue
                metadata = item.get("metadata")
                role = None
                if isinstance(metadata, dict):
                    role = metadata.get("relation") or metadata.get("role")
                mentions.append((kind, str(value), role))

            if mentions:
                await apply_mentions(
                    session, str(user_id), str(memory_id), mentions
                )
                created += len(mentions)

            await session.execute(
                text(
                    "UPDATE memories SET entities_backfilled = TRUE WHERE id = :i"
                ),
                {"i": memory_id},
            )

        await session.commit()
        if created:
            print(f"Backfilled {created} entity mentions from structured_content.")

tags_metadata = [
    {
        "name": "health",
        "description": "Health check endpoints",
    },
    {
        "name": "auth",
        "description": "User authentication (login, register, token refresh)",
    },
    {
        "name": "memories",
        "description": "Memory capture, retrieval, editing, deletion",
    },
    {
        "name": "search",
        "description": "Hybrid search (full-text, semantic, filters)",
    },
    {
        "name": "stories",
        "description": "Story generation and retrieval",
    },
    {
        "name": "timeline",
        "description": "Timeline view of memories",
    },
    {
        "name": "insights",
        "description": "User insights and statistics",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events (startup/shutdown)."""
    # Startup
    print("MEMIND application starting...")
    # Must run before create_all: the legacy entities table cannot be migrated
    # in place, only dropped and recreated with the new shape.
    await _drop_legacy_entity_table()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _apply_pending_migrations()
    print("Database tables ensured.")
    scheduler.start()
    print("APScheduler started.")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    print("APScheduler shut down.")
    print("MEMIND application shutting down...")


# Create FastAPI app
app = FastAPI(
    title="MEMIND API",
    description="AI-powered memory capture and enhancement platform",
    version="0.1.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
    ],  # Add frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Check if API is running."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/health/ollama", tags=["health"])
async def ollama_health_check():
    """Check if the configured Ollama API is reachable."""
    api_base, model, api_key = _ollama_config()
    url = f"{api_base}/models" if api_base.endswith("/v1") else f"{api_base}/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            models = [m.get("id", m.get("model")) for m in data.get("data", [])]
            return {
                "reachable": True,
                "base_url": api_base,
                "configured_model": model,
                "available_models": models[:10],
            }
    except Exception as exc:
        return {
            "reachable": False,
            "base_url": api_base,
            "configured_model": model,
            "error": str(exc),
        }


# Include routes
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(memories.router, prefix="/api", tags=["memories"])
app.include_router(stories.router, prefix="/api", tags=["stories"])
app.include_router(timeline.router, prefix="/api", tags=["timeline"])
app.include_router(insights.router, prefix="/api", tags=["insights"])
app.include_router(review.router, prefix="/api", tags=["review"])
app.include_router(entities.router, prefix="/api", tags=["entities"])
app.include_router(tellings.router, prefix="/api", tags=["tellings"])
app.include_router(wiki.router, prefix="/api", tags=["wiki"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
