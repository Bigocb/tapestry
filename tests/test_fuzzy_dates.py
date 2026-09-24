"""Tests for fuzzy/coarse date handling.

A memory like "sometime in middle school" or "back in the 80s" has real but
imprecise time information. It must be preserved as a period (decade / range /
label) rather than being flattened into a fake exact date or treated as a
missing date and hidden in the review queue.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.main import app
from app.db import Base, User, Memory, get_db
from app.security import hash_password
from app.agents.capture import resolve_date


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
def client(test_db):
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def setup_users(test_db):
    async def _setup():
        user1 = User(
            username="alice",
            email="alice@example.com",
            password_hash=hash_password("password123"),
        )
        user2 = User(
            username="bob",
            email="bob@example.com",
            password_hash=hash_password("password456"),
        )
        test_db.add(user1)
        test_db.add(user2)
        await test_db.commit()
        await test_db.refresh(user1)
        await test_db.refresh(user2)
        return user1, user2

    return _setup


@pytest.fixture
def get_auth_token(client):
    def _get_token(username: str, password: str):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        return response.json()["access_token"]

    return _get_token


async def _seed_memory(
    session,
    user_id,
    raw_input,
    title,
    event_date=None,
    date_precision=None,
    event_date_end=None,
    date_label=None,
    needs_review=False,
    needs_event=False,
):
    memory = Memory(
        raw_input=raw_input,
        input_type="text",
        user_id=user_id,
        structured_content={"title": title, "summary": raw_input},
        tags=[],
        mood="neutral",
        importance_level=5,
        processing_state="enriched",
        related_memory_ids=[],
        event_date=event_date,
        date_precision=date_precision,
        event_date_end=event_date_end,
        date_label=date_label,
        needs_review=needs_review,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


class TestResolveDateUnit:
    """Unit coverage of the resolver's fuzzy branches."""

    def test_year_range_is_preserved_not_collapsed(self):
        r = resolve_date("middle school sometime around 1987 to 1990")
        assert r.precision == "range"
        assert r.event_date.year == 1987
        assert r.event_date_end.year == 1990
        assert "1987" in r.label and "1990" in r.label

    def test_decade(self):
        r = resolve_date("Back in the 80s we lived in Ohio")
        assert r.precision == "decade"
        assert r.event_date.year == 1980
        assert r.event_date_end.year == 1989
        assert r.label == "1980s"

    def test_early_decade_narrows_the_range(self):
        r = resolve_date("In the early 90s I moved to Raleigh")
        assert r.precision == "decade"
        assert r.event_date.year == 1990
        assert r.event_date_end.year == 1993
        assert r.label == "early 1990s"

    def test_late_decade(self):
        r = resolve_date("late 70s were wild")
        assert r.label == "late 1970s"
        assert r.event_date.year == 1977

    def test_explicit_four_digit_decade(self):
        r = resolve_date("the 1980s were great")
        assert r.event_date.year == 1980
        assert r.label == "1980s"

    def test_named_life_period_without_years(self):
        r = resolve_date("Sometime in middle school I met my best friend")
        assert r.event_date is None
        assert r.label == "Middle school"
        # No anchor, but it is still a known period, not 'unknown'.
        assert r.label is not None

    def test_plain_mention_does_not_fabricate_a_period(self):
        """A passing mention of high school must not invent a date."""
        r = resolve_date("My high school was large and old.")
        assert r.label is None
        assert r.event_date is None

    def test_exact_date_still_exact(self):
        r = resolve_date("On July 29, 1976 I was born")
        assert r.precision == "exact"
        assert r.event_date.day == 29
        assert r.event_date_end is None

    def test_month_only_precision(self):
        r = resolve_date("I visited Paris in July 2024")
        assert r.precision == "month"

    def test_bare_year_precision(self):
        r = resolve_date("Back in 2019 I started guitar")
        assert r.precision == "year"

    def test_no_time_returns_unknown(self):
        r = resolve_date("Just a thought about the project")
        assert r.precision == "unknown"
        assert r.event_date is None
        assert r.label is None


class TestAgentsPreserveFuzzyPeriods:
    """The refinement/enrichment agents must not erase fuzzy-period data.

    Both agents rebuild a StructuredMemory from LLM output. They previously
    carried only event_date, so a captured decade/range/label was silently
    flattened to a point date (or dropped entirely) during processing.
    """

    @pytest.mark.asyncio
    async def test_refinement_preserves_label_and_precision(self, monkeypatch):
        from app.agents import refinement

        async def fake_call(messages):
            # The model only returns a point date; fuzzy fields must survive
            # via the fallback.
            return {"title": "Ohio", "summary": "Lived in Ohio.", "event_date": None}

        monkeypatch.setattr(refinement, "_call_ollama_chat", fake_call)

        current = {
            "title": "Ohio",
            "summary": "Lived in Ohio.",
            "entities": [],
            "mood": None,
            "importance_level": 5,
            "initial_tags": [],
            "event_date": "1980-01-01T00:00:00Z",
            "date_precision": "decade",
            "event_date_end": "1989-12-31T00:00:00Z",
            "date_label": "1980s",
        }

        result = await refinement.refine_memory(
            raw_input="Back in the 80s we lived in Ohio",
            structured_content=current,
            recent_memories=[],
        )

        assert result.date_precision == "decade"
        assert result.date_label == "1980s"
        assert result.event_date_end is not None

    @pytest.mark.asyncio
    async def test_enrichment_preserves_label(self, monkeypatch):
        from app.agents import enrichment

        async def fake_call(messages):
            return {"title": "Ohio", "summary": "Lived in Ohio.", "event_date": None}

        monkeypatch.setattr(enrichment, "_call_ollama_chat", fake_call)

        current = {
            "title": "Ohio",
            "summary": "Lived in Ohio.",
            "entities": [],
            "mood": None,
            "importance_level": 5,
            "initial_tags": [],
            "event_date": "1980-01-01T00:00:00Z",
            "date_precision": "decade",
            "event_date_end": "1989-12-31T00:00:00Z",
            "date_label": "1980s",
        }

        result, _ = await enrichment.enrich_memory(
            memory=current,
            similar_memories=[],
        )

        assert result.date_label == "1980s"
        assert result.date_precision == "decade"


class TestFuzzyDatesInApi:
    """Fuzzy periods surface through the API and the timeline."""

    @pytest.mark.asyncio
    async def test_range_memory_appears_on_timeline(
        self, client, test_db, setup_users, get_auth_token
    ):
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            "middle school 87-90",
            "Middle school",
            event_date=datetime(1987, 1, 1, tzinfo=timezone.utc),
            date_precision="range",
            event_date_end=datetime(1990, 12, 31, tzinfo=timezone.utc),
            date_label="Middle school (1987-1990)",
        )

        response = client.get(
            "/api/timeline", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["date_precision"] == "range"
        assert items[0]["date_label"] == "Middle school (1987-1990)"
        assert items[0]["event_date_end"] is not None

    @pytest.mark.asyncio
    async def test_label_only_memory_appears_on_timeline(
        self, client, test_db, setup_users, get_auth_token
    ):
        """A known period must not be hidden just because it lacks an anchor."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            "Sometime in middle school I met my best friend",
            "Best friend",
            event_date=None,
            date_precision="unknown",
            date_label="Middle school",
        )

        response = client.get(
            "/api/timeline", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["date_label"] == "Middle school"

    @pytest.mark.asyncio
    async def test_truly_undated_memory_stays_off_timeline(
        self, client, test_db, setup_users, get_auth_token
    ):
        """No time information at all still belongs in review, not timeline."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            "Just a thought",
            "Thought",
            needs_review=True,
        )

        response = client.get(
            "/api/timeline", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.json() == []

    @pytest.mark.asyncio
    async def test_date_range_filter_excludes_label_only(
        self, client, test_db, setup_users, get_auth_token
    ):
        """A range filter can't place an anchorless memory, so it is excluded."""
        user1, _ = await setup_users()
        token = get_auth_token("alice", "password123")
        await _seed_memory(
            test_db,
            str(user1.id),
            "sometime in middle school",
            "LabelOnly",
            date_label="Middle school",
        )

        response = client.get(
            "/api/timeline?start_date=1980-01-01T00:00:00&end_date=2000-01-01T00:00:00",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_capture_with_fuzzy_period_is_not_flagged_for_review(
        self, client, test_db, setup_users, get_auth_token, monkeypatch
    ):
        """A decade is a real answer, so it should not enter the review queue."""
        await setup_users()
        token = get_auth_token("alice", "password123")

        from app.models.schemas import StructuredMemory

        async def fake_structure(raw_input: str) -> StructuredMemory:
            resolved = resolve_date(raw_input)
            return StructuredMemory(
                title="The 80s",
                summary=raw_input,
                entities=[],
                mood=None,
                importance_level=5,
                initial_tags=["test"],
                event_date=resolved.event_date,
                date_precision=resolved.precision,
                event_date_end=resolved.event_date_end,
                date_label=resolved.label,
            )

        monkeypatch.setattr("app.routes.memories.structure_memory", fake_structure)
        monkeypatch.setattr(
            "app.routes.memories._schedule_refinement", lambda *a, **k: None
        )

        response = client.post(
            "/api/memories/capture/text",
            json={"raw_input": "Back in the 80s we lived in Ohio"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["date_precision"] == "decade"
        assert data["date_label"] == "1980s"
        assert data["needs_review"] is False
