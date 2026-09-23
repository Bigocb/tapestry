"""Worker functions that execute tracked agent jobs.

These functions are called by APScheduler and are responsible for:
- Loading the JobStatus row
- Running the appropriate agent (refinement or enrichment)
- Updating memory state and job progress
- Handling errors and recording failure details
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.jobs.scheduler import (
    get_session_factory,
    update_job_status,
    create_job_status,
    schedule_job,
    scheduler,
)
from app.db import Memory, JobStatus
from app.agents.embeddings import (
    cosine_similarity,
    deserialize_embedding,
    generate_embedding,
    serialize_embedding,
)
from app.agents.enrichment import enrich_memory
from app.agents.refinement import refine_memory


async def _fetch_recent_memories(
    db: AsyncSession, user_id: str, exclude_memory_id: str, limit: int = 5
) -> list[dict]:
    """Fetch recent memories for context during refinement."""
    from sqlalchemy import desc

    stmt = (
        select(Memory)
        .where(Memory.user_id == user_id)
        .where(Memory.id != exclude_memory_id)
        .order_by(desc(Memory.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    context = []
    for mem in memories:
        content = mem.structured_content or {}
        context.append(
            {
                "title": content.get("title", "Untitled")
                if isinstance(content, dict)
                else "Untitled",
                "summary": content.get("summary", "")
                if isinstance(content, dict)
                else "",
                "entities": content.get("entities", [])
                if isinstance(content, dict)
                else [],
                "created_at": mem.created_at.isoformat() if mem.created_at else None,
            }
        )
    return context


async def _generate_embedding_for_memory(memory: Memory) -> None:
    """Generate and attach an embedding from the memory's searchable text."""
    content = memory.structured_content or {}
    if isinstance(content, dict):
        searchable_parts = [
            content.get("title", ""),
            content.get("summary", ""),
            memory.raw_input,
        ]
    else:
        searchable_parts = [memory.raw_input]

    searchable_text = " ".join(part for part in searchable_parts if part).strip()
    embedding = await generate_embedding(searchable_text)
    memory.embedding = serialize_embedding(embedding) if embedding else None


async def _find_similar_memories(
    db: AsyncSession,
    memory: Memory,
    exclude_memory_id: str,
    limit: int = 5,
) -> list[dict]:
    """Find top-k memories most similar to the given memory by embedding."""
    from sqlalchemy import desc

    target_embedding = deserialize_embedding(memory.embedding)
    if not target_embedding:
        return []

    stmt = (
        select(Memory)
        .where(Memory.user_id == memory.user_id)
        .where(Memory.id != exclude_memory_id)
        .where(Memory.embedding.is_not(None))
        .order_by(desc(Memory.created_at))
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()

    scored = []
    for mem in memories:
        embedding = deserialize_embedding(mem.embedding)
        if not embedding or len(embedding) != len(target_embedding):
            continue
        score = cosine_similarity(target_embedding, embedding)
        scored.append((score, mem))

    scored.sort(key=lambda item: item[0], reverse=True)
    top = scored[:limit]

    similar = []
    for score, mem in top:
        content = mem.structured_content or {}
        similar.append(
            {
                "memory_id": str(mem.id),
                "title": content.get("title") if isinstance(content, dict) else None,
                "summary": content.get("summary")
                if isinstance(content, dict)
                else None,
                "score": round(float(score), 4),
            }
        )
    return similar


async def _run_refinement(memory: Memory, db: AsyncSession) -> None:
    """Run the Refinement Agent on a memory."""
    recent_memories = await _fetch_recent_memories(
        db=db,
        user_id=str(memory.user_id),
        exclude_memory_id=str(memory.id),
    )
    refined = await refine_memory(
        raw_input=memory.raw_input,
        structured_content=memory.structured_content or {},
        recent_memories=recent_memories,
    )

    memory.structured_content = refined.model_dump(mode="json")
    memory.mood = refined.mood
    memory.importance_level = refined.importance_level
    memory.tags = refined.initial_tags
    memory.event_date = refined.event_date


async def _run_enrichment(memory: Memory, db: AsyncSession) -> None:
    """Run the Enrichment Agent on a memory using similar memories as context."""
    await _generate_embedding_for_memory(memory)

    similar_memories = await _find_similar_memories(
        db=db,
        memory=memory,
        exclude_memory_id=str(memory.id),
        limit=5,
    )

    enriched, related_ids = await enrich_memory(
        memory=memory.structured_content or {},
        similar_memories=similar_memories,
    )

    memory.structured_content = enriched.model_dump(mode="json")
    memory.mood = enriched.mood
    memory.importance_level = enriched.importance_level
    memory.tags = enriched.initial_tags
    memory.event_date = enriched.event_date
    memory.related_memory_ids = related_ids


async def run_tracked_job(job_id: str) -> None:
    """Execute the JobStatus row with the given id.

    This is the entry point APScheduler calls. It loads the job, runs the
    requested agent stage, updates memory state, and records completion or
    failure.
    """
    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(JobStatus).where(JobStatus.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return

        memory = None
        if job.memory_id:
            mem_result = await db.execute(
                select(Memory).where(Memory.id == job.memory_id)
            )
            memory = mem_result.scalar_one_or_none()

        try:
            await update_job_status(db, job, "running", progress=0.1)

            if job.task_type == "refinement":
                if memory is None:
                    raise ValueError("Memory not found for refinement job")
                await _run_refinement(memory, db)
                memory.processing_state = "refined"
                await update_job_status(db, job, "completed", progress=1.0)

                # Chain enrichment job.
                enrichment_job = await create_job_status(
                    db=db,
                    user_id=str(job.user_id),
                    memory_id=str(memory.id),
                    task_type="enrichment",
                    status="pending",
                )
                # Chain enrichment job. Only schedule it if the scheduler is
                # actually running; otherwise run inline. Doing both would
                # execute enrichment twice and race on the memory row.
                if scheduler.running:
                    schedule_job(str(enrichment_job.id))
                else:
                    await run_tracked_job(str(enrichment_job.id))

            elif job.task_type == "enrichment":
                if memory is None:
                    raise ValueError("Memory not found for enrichment job")
                await _run_enrichment(memory, db)
                memory.processing_state = "enriched"
                await update_job_status(db, job, "completed", progress=1.0)

            else:
                raise ValueError(f"Unknown task_type: {job.task_type}")

            await db.commit()
        except Exception as exc:
            # A flush failure leaves the session rolled back and its ORM
            # instances expired. Roll back explicitly, then re-fetch the rows by
            # id (touching the expired instances directly would trigger a lazy
            # sync load and raise MissingGreenlet).
            await db.rollback()

            fresh_job = (
                await db.execute(select(JobStatus).where(JobStatus.id == job_id))
            ).scalar_one_or_none()

            if memory is not None:
                fresh_memory = (
                    await db.execute(
                        select(Memory).where(Memory.id == job.memory_id)
                    )
                ).scalar_one_or_none()
                if fresh_memory is not None:
                    fresh_memory.processing_state = f"{fresh_job.task_type}_failed"

            if fresh_job is not None:
                await update_job_status(db, fresh_job, "failed", error=str(exc))
            await db.commit()
            # Do not propagate: background jobs should record failure without
            # breaking the capture response.
