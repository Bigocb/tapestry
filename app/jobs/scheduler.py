"""APScheduler setup and background job helpers.

The scheduler is started on application startup and is used to queue
async agent work (refinement, enrichment) so that capture endpoints return
immediately. In test environments the same database is used by overriding
`BackgroundSessionLocal` in `app.routes.memories`.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.db.connection import engine
from app.db import Memory, JobStatus

scheduler = AsyncIOScheduler(timezone=timezone.utc)

BackgroundSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def get_session_factory() -> async_sessionmaker:
    """Return the session factory used by background jobs.

    Tests override this by monkeypatching `app.jobs.scheduler.BackgroundSessionLocal`.
    """
    return BackgroundSessionLocal


async def create_job_status(
    db: AsyncSession,
    user_id: str,
    memory_id: str,
    task_type: str,
    status: str = "pending",
    overrides: dict | None = None,
) -> JobStatus:
    """Create and persist a JobStatus row.

    ``overrides`` carries user-supplied field values that must survive the
    agent run (e.g. a manual mood correction made alongside a text edit).
    """
    job = JobStatus(
        user_id=user_id,
        memory_id=memory_id,
        task_type=task_type,
        status=status,
        progress=0.0,
        overrides=overrides,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def update_job_status(
    db: AsyncSession,
    job: JobStatus,
    status: str,
    progress: float | None = None,
    error: str | None = None,
) -> None:
    """Update a JobStatus row in place."""
    job.status = status
    if progress is not None:
        job.progress = progress
    if error is not None:
        job.error = error
    await db.commit()


async def _load_memory(db: AsyncSession, memory_id: str) -> Memory | None:
    """Fetch a memory row by id, returning None if missing."""
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    return result.scalar_one_or_none()


def schedule_job(job_id: str, run_time: datetime | None = None) -> None:
    """Schedule a wrapper job that executes the tracked job by id.

    This indirection lets us keep agent logic in `app.routes.memories` while
    still leveraging APScheduler for execution. Jobs run immediately by default
    (run_time = now) so that TestClient executes them synchronously after the
    response.
    """
    from app.jobs.worker import run_tracked_job

    run_time = run_time or datetime.now(timezone.utc)
    scheduler.add_job(
        run_tracked_job,
        trigger=DateTrigger(run_date=run_time),
        id=f"job-{job_id}-{run_time.timestamp()}",
        replace_existing=True,
        args=[job_id],
        misfire_grace_time=60,
    )
