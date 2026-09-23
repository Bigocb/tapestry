"""Tests for APScheduler-based async agent jobs (Issue 26)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from uuid import UUID

from datetime import datetime, timezone

from app.main import app
from app.db import Base, User, Memory, JobStatus, get_db
from app.security import hash_password
from app.models.schemas import StructuredMemory, EntityData

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    """Create an in-memory test database."""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    AsyncSessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def client(test_db):
    """FastAPI test client with overridden database dependency."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.routes import memories

    async def override_get_db():
        yield test_db

    test_factory = async_sessionmaker(
        bind=test_db.bind,
        class_=type(test_db),
        expire_on_commit=False,
        autoflush=False,
    )
    from app.jobs import scheduler as scheduler_module

    original_factory = scheduler_module.BackgroundSessionLocal
    scheduler_module.BackgroundSessionLocal = test_factory

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    scheduler_module.BackgroundSessionLocal = original_factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def setup_users(test_db):
    """Create test users in database."""

    async def _setup():
        user = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        test_db.add(user)
        await test_db.commit()
        await test_db.refresh(user)
        return user

    return _setup


@pytest.fixture
def get_auth_token(client):
    """Get JWT token for a user."""

    def _get_token(username: str, password: str):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return response.json()["access_token"]

    return _get_token


@pytest.fixture
def fake_structure_memory(monkeypatch):
    """Replace the Capture Agent with a deterministic stub."""

    async def _fake(raw_input: str):
        return StructuredMemory(
            title="Structured: " + raw_input[:50],
            summary=raw_input,
            entities=[EntityData(type="concept", value="test")],
            mood="neutral",
            importance_level=5,
            initial_tags=["test"],
        )

    monkeypatch.setattr("app.routes.memories.structure_memory", _fake)


class TestCaptureSchedulesRefinementJob:
    """Tracer bullet: capture endpoint creates a completed refinement job."""

    @pytest.mark.asyncio
    async def test_text_capture_creates_refinement_job_status(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        fake_structure_memory,
    ):
        """After text capture, a JobStatus row for refinement is completed."""
        user = await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Need to buy groceries for the weekend dinner."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        # Background tasks run synchronously after the response in TestClient.
        stmt = select(JobStatus).where(JobStatus.memory_id == memory_id)
        result = await test_db.execute(stmt)
        jobs = result.scalars().all()

        assert len(jobs) >= 1
        refinement_jobs = [job for job in jobs if job.task_type == "refinement"]
        assert len(refinement_jobs) == 1
        assert refinement_jobs[0].user_id == user.id
        assert refinement_jobs[0].status == "completed"


class TestPipelineReachesEnriched:
    """Capture schedules refinement; refinement success schedules enrichment."""

    @pytest.mark.asyncio
    async def test_capture_pipeline_reaches_enriched(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        fake_structure_memory,
    ):
        """After text capture, the memory reaches state 'enriched'."""
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Need to buy groceries for the weekend dinner."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        stmt = select(Memory).where(Memory.id == UUID(memory_id))
        result = await test_db.execute(stmt)
        memory = result.scalar_one_or_none()

        assert memory is not None
        assert memory.processing_state == "enriched"
        assert memory.embedding is not None
        assert isinstance(memory.related_memory_ids, list)

    @pytest.mark.asyncio
    async def test_capture_pipeline_creates_enrichment_job(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        fake_structure_memory,
    ):
        """After refinement succeeds, an enrichment JobStatus row is completed."""
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Need to buy groceries for the weekend dinner."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        stmt = select(JobStatus).where(JobStatus.memory_id == memory_id)
        result = await test_db.execute(stmt)
        jobs = result.scalars().all()

        enrichment_jobs = [job for job in jobs if job.task_type == "enrichment"]
        assert len(enrichment_jobs) == 1
        assert enrichment_jobs[0].status == "completed"


class TestJobFailureHandling:
    """Agent failures are recorded in JobStatus and leave memory in failed state."""

    @pytest.mark.asyncio
    async def test_refinement_failure_records_failed_status(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        fake_structure_memory,
        monkeypatch,
    ):
        """When refinement fails, the job is marked failed and memory state reflects it."""
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def boom(*args, **kwargs):
            raise RuntimeError("ollama unreachable")

        from app.jobs import worker

        monkeypatch.setattr(worker, "refine_memory", boom)

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Need to buy groceries for the weekend dinner."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        stmt = select(JobStatus).where(JobStatus.memory_id == memory_id)
        result = await test_db.execute(stmt)
        jobs = result.scalars().all()

        refinement_jobs = [job for job in jobs if job.task_type == "refinement"]
        assert len(refinement_jobs) == 1
        assert refinement_jobs[0].status == "failed"
        assert "ollama unreachable" in refinement_jobs[0].error

        mem_result = await test_db.execute(select(Memory).where(Memory.id == UUID(memory_id)))
        memory = mem_result.scalar_one_or_none()
        assert memory is not None
        assert memory.processing_state == "refinement_failed"


class TestDatetimeContentPersists:
    """Regression: structured_content containing a datetime must persist.

    StructuredMemory.event_date is a datetime. Writing it through the job
    worker previously used model_dump() (not mode='json'), which is not
    JSON-serializable, so the flush raised and the whole job transaction
    rolled back -- leaving the memory stuck at 'capturing'.
    """

    @pytest.mark.asyncio
    async def test_refinement_with_event_date_reaches_enriched(
        self,
        client,
        test_db,
        setup_users,
        get_auth_token,
        monkeypatch,
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def fake_refine(raw_input, structured_content, recent_memories):
            return StructuredMemory(
                title="Dated memory",
                summary=raw_input,
                entities=[EntityData(type="date", value="July 29, 1976")],
                mood="neutral",
                importance_level=6,
                initial_tags=["birth"],
                event_date=datetime(1976, 7, 29, tzinfo=timezone.utc),
            )

        from app.jobs import worker

        monkeypatch.setattr(worker, "refine_memory", fake_refine)

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "I was born on July 29, 1976."},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        memory_id = response.json()["id"]

        stmt = select(Memory).where(Memory.id == UUID(memory_id))
        result = await test_db.execute(stmt)
        memory = result.scalar_one_or_none()

        assert memory is not None
        # Must not be stuck at 'capturing' (the pre-fix symptom).
        assert memory.processing_state == "enriched"
        assert isinstance(memory.structured_content, dict)
        assert memory.event_date is not None
        # The persisted content must be JSON-serializable.
        import json

        json.dumps(memory.structured_content)


class TestEditTriggersReprocessing:
    """Editing the source text requeues the memory; metadata edits do not."""

    async def _capture(self, client, token, text="Original text about the trip."):
        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": text},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        return response.json()["id"]

    @pytest.mark.asyncio
    async def test_editing_raw_input_reruns_agents(
        self, client, test_db, setup_users, get_auth_token, fake_structure_memory
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")
        memory_id = await self._capture(client, token)

        # One refinement job from capture.
        before = await test_db.execute(
            select(JobStatus).where(
                JobStatus.memory_id == memory_id,
                JobStatus.task_type == "refinement",
            )
        )
        assert len(before.scalars().all()) == 1

        response = client.patch(
            f"/api/memories/{memory_id}",
            json={"raw_input": "A completely different memory about work."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        after = await test_db.execute(
            select(JobStatus).where(
                JobStatus.memory_id == memory_id,
                JobStatus.task_type == "refinement",
            )
        )
        refinement_jobs = after.scalars().all()
        assert len(refinement_jobs) == 2

        mem_result = await test_db.execute(
            select(Memory).where(Memory.id == UUID(memory_id))
        )
        assert mem_result.scalar_one().processing_state == "enriched"

    @pytest.mark.asyncio
    async def test_metadata_edit_does_not_rerun_agents(
        self, client, test_db, setup_users, get_auth_token, fake_structure_memory
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")
        memory_id = await self._capture(client, token)

        response = client.patch(
            f"/api/memories/{memory_id}",
            json={"mood": "happy", "importance_level": 3, "title": "Manual title"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        jobs = await test_db.execute(
            select(JobStatus).where(
                JobStatus.memory_id == memory_id,
                JobStatus.task_type == "refinement",
            )
        )
        # Still just the capture-time job.
        assert len(jobs.scalars().all()) == 1

        mem_result = await test_db.execute(
            select(Memory).where(Memory.id == UUID(memory_id))
        )
        memory = mem_result.scalar_one()
        assert memory.mood == "happy"
        assert memory.importance_level == 3

    @pytest.mark.asyncio
    async def test_user_edits_survive_reprocessing(
        self, client, test_db, setup_users, get_auth_token, fake_structure_memory
    ):
        """A manual correction sent with a text edit must not be clobbered."""
        await setup_users()
        token = get_auth_token("alice", "password123")
        memory_id = await self._capture(client, token)

        response = client.patch(
            f"/api/memories/{memory_id}",
            json={
                "raw_input": "Rewritten source text.",
                "mood": "determined",
                "importance_level": 9,
                "title": "My chosen title",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        mem_result = await test_db.execute(
            select(Memory).where(Memory.id == UUID(memory_id))
        )
        memory = mem_result.scalar_one()
        # The stub agents would set mood=neutral/importance=5/title=Structured:...
        # so if overrides failed, these would not match.
        assert memory.mood == "determined"
        assert memory.importance_level == 9
        assert memory.structured_content["title"] == "My chosen title"
