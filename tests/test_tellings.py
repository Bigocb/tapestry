"""Tests for Tellings (Issue 28): one recounting becomes many memories.

A telling is a recounting. Its segments are *proposed* memories, held outside
the ``memories`` table until the user commits them. These tests exercise the
public API only.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, User, get_db
from app.security import hash_password
from app.agents.telling import ProposedSegment, SegmentationResult
from app.models.schemas import StructuredMemory, EntityData


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

TRANSCRIPT = (
    "In the summer of 1985 we drove down to Florida. The next day we went to "
    "Disney. Two years later I started college and met Dave."
)


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

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def setup_users(test_db):
    """Create test users in database."""

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
def fake_segmentation(monkeypatch):
    """Replace the segmentation pass with a deterministic stub.

    The telling pipeline splits the account once, on the way in, so the stub
    keeps tests off the network and makes the resulting segment predictable.
    It returns a single segment covering the whole account, which is the
    fallback behaviour a model outage produces.
    """

    async def _fake(transcript: str):
        return SegmentationResult(segments=[
            ProposedSegment(
                text=transcript,
                structured=StructuredMemory(
                    title="Structured: " + transcript[:50],
                    summary=transcript,
                    entities=[EntityData(type="concept", value="test")],
                    mood="neutral",
                    importance_level=5,
                    initial_tags=["test"],
                ),
            )
        ])

    monkeypatch.setattr("app.routes.tellings.segment_transcript", _fake)


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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _structured_memory(title: str) -> StructuredMemory:
    return StructuredMemory(
        title=title,
        summary=title,
        entities=[],
        importance_level=5,
        initial_tags=[],
    )


class TestSegmentedCapture:
    """One recounting becomes one row per proposed memory."""

    async def test_stores_one_row_per_proposed_segment(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def fake_segment(transcript: str):
            return SegmentationResult(segments=[
                ProposedSegment(
                    text="In the summer of 1985 we drove down to Florida.",
                    structured=_structured_memory("Trip to Florida"),
                ),
                ProposedSegment(
                    text="The next day we went to Disney.",
                    structured=_structured_memory("Disney"),
                ),
            ])

        monkeypatch.setattr("app.routes.tellings.segment_transcript", fake_segment)

        response = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        )

        assert response.status_code == 201
        segments = response.json()["segments"]
        assert [segment["text"] for segment in segments] == [
            "In the summer of 1985 we drove down to Florida.",
            "The next day we went to Disney.",
        ]
        assert [segment["ordinal"] for segment in segments] == [0, 1]
        assert [segment["title"] for segment in segments] == [
            "Trip to Florida",
            "Disney",
        ]


class TestTellingFrame:
    """The period the account is about belongs to the telling."""

    async def test_the_frame_is_stored_on_the_telling(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def fake_segmentation(transcript: str):
            return SegmentationResult(
                segments=[
                    ProposedSegment(
                        text=transcript,
                        structured=_structured_memory("Born in Conway"),
                        date_settled=True,
                    )
                ],
                frame_label="first month in high school",
            )

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", fake_segmentation
        )

        response = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        )

        assert response.status_code == 201
        assert response.json()["frame_label"] == "first month in high school"


class TestInheritedFrameOutcomes:
    """Inheriting a period is what keeps a memory out of the review queue."""

    async def _commit_one_segment(
        self, client, token, monkeypatch, structured
    ):
        async def fake_segmentation(transcript: str):
            return SegmentationResult(
                segments=[
                    ProposedSegment(
                        text=transcript,
                        structured=structured,
                        date_settled=True,
                    )
                ],
                frame_label=structured.date_label,
            )

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", fake_segmentation
        )
        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        committed = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        ).json()
        return client.get(
            f"/api/memories/{committed['segments'][0]['memory_id']}",
            headers=_auth(token),
        ).json()

    async def test_an_inherited_period_keeps_the_memory_out_of_review(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        memory = await self._commit_one_segment(
            client,
            token,
            monkeypatch,
            StructuredMemory(
                title="Lockers",
                summary="The first day.",
                entities=[],
                importance_level=5,
                initial_tags=[],
                date_label="first month in high school",
            ),
        )

        assert memory["date_label"] == "first month in high school"
        assert memory["needs_review"] is False

    async def test_no_signal_and_no_frame_still_reaches_the_review_queue(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        memory = await self._commit_one_segment(
            client,
            token,
            monkeypatch,
            StructuredMemory(
                title="Something happened",
                summary="No idea when.",
                entities=[],
                importance_level=5,
                initial_tags=[],
            ),
        )

        assert memory["needs_review"] is True
        assert memory["review_reason"] == "missing_date"


class TestReshapeSegments:
    """A proposed split is a draft, and drafts are meant to be corrected."""

    async def _draft(self, client, token, monkeypatch, texts):
        async def fake_segmentation(transcript: str):
            return SegmentationResult(
                segments=[
                    ProposedSegment(
                        text=text,
                        structured=_structured_memory(f"Part {index + 1}"),
                    )
                    for index, text in enumerate(texts)
                ]
            )

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", fake_segmentation
        )
        return client.post(
            "/api/tellings",
            json={"raw_transcript": " ".join(texts)},
            headers=_auth(token),
        ).json()

    async def test_merging_two_adjacent_segments(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(
            client,
            token,
            monkeypatch,
            ["First memory.", "Second memory.", "Third memory."],
        )
        first, second = draft["segments"][0]["id"], draft["segments"][1]["id"]

        response = client.post(
            f"/api/tellings/{draft['id']}/segments/merge",
            json={"segment_ids": [first, second]},
            headers=_auth(token),
        )

        assert response.status_code == 200
        segments = response.json()["segments"]
        assert len(segments) == 2
        assert segments[0]["text"] == "First memory. Second memory."
        # Ordinals close the gap the merge left.
        assert [segment["ordinal"] for segment in segments] == [0, 1]
        assert segments[1]["text"] == "Third memory."

    async def test_deleting_a_segment_renumbers_the_rest(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(
            client, token, monkeypatch, ["One.", "Two.", "Three."]
        )
        middle = draft["segments"][1]["id"]

        response = client.delete(
            f"/api/tellings/{draft['id']}/segments/{middle}",
            headers=_auth(token),
        )

        assert response.status_code == 200
        segments = response.json()["segments"]
        assert [segment["text"] for segment in segments] == ["One.", "Three."]
        assert [segment["ordinal"] for segment in segments] == [0, 1]

    async def test_segments_can_be_reordered(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(
            client, token, monkeypatch, ["One.", "Two.", "Three."]
        )
        reversed_ids = [
            segment["id"] for segment in reversed(draft["segments"])
        ]

        response = client.post(
            f"/api/tellings/{draft['id']}/segments/reorder",
            json={"segment_ids": reversed_ids},
            headers=_auth(token),
        )

        assert response.status_code == 200
        segments = response.json()["segments"]
        assert [segment["text"] for segment in segments] == [
            "Three.",
            "Two.",
            "One.",
        ]
        assert [segment["ordinal"] for segment in segments] == [0, 1, 2]

    async def test_splitting_a_segment_at_an_offset(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(
            client, token, monkeypatch, ["First part and second part."]
        )
        segment_id = draft["segments"][0]["id"]

        response = client.post(
            f"/api/tellings/{draft['id']}/segments/{segment_id}/split",
            json={"at": 15},
            headers=_auth(token),
        )

        assert response.status_code == 200
        segments = response.json()["segments"]
        assert len(segments) == 2
        assert segments[0]["text"] == "First part and"
        assert segments[1]["text"] == "second part."
        assert [segment["ordinal"] for segment in segments] == [0, 1]

    async def test_a_committed_telling_refuses_structural_edits(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(client, token, monkeypatch, ["One.", "Two."])
        ids = [segment["id"] for segment in draft["segments"]]
        client.post(f"/api/tellings/{draft['id']}/commit", headers=_auth(token))

        response = client.post(
            f"/api/tellings/{draft['id']}/segments/merge",
            json={"segment_ids": ids},
            headers=_auth(token),
        )

        # Its segments are memories now; moving their boundaries would orphan
        # them.
        assert response.status_code == 409


class TestTellingProvenance:
    """What a telling produced, and how to take it back."""

    async def _commit(
        self, client, token, monkeypatch, texts=("One.", "Two.")
    ):
        async def fake_segmentation(transcript: str):
            return SegmentationResult(
                segments=[
                    ProposedSegment(
                        text=text, structured=_structured_memory(text)
                    )
                    for text in texts
                ]
            )

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", fake_segmentation
        )
        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        client.post(f"/api/tellings/{draft['id']}/commit", headers=_auth(token))
        return draft

    async def test_the_memories_a_telling_produced_can_be_listed(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._commit(client, token, monkeypatch)

        response = client.get(
            f"/api/tellings/{draft['id']}/memories", headers=_auth(token)
        )

        assert response.status_code == 200
        assert [memory["raw_input"] for memory in response.json()] == [
            "One.",
            "Two.",
        ]

    async def test_deleting_the_batch_keeps_the_telling_and_returns_it_to_draft(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._commit(client, token, monkeypatch)

        response = client.delete(
            f"/api/tellings/{draft['id']}/memories", headers=_auth(token)
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "draft"
        assert body["raw_transcript"] == TRANSCRIPT
        assert [segment["memory_id"] for segment in body["segments"]] == [
            None,
            None,
        ]

        assert client.get("/api/memories", headers=_auth(token)).json() == []

        # The transcript survived, so the same telling can be committed again.
        again = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        )
        assert again.status_code == 200
        assert len(client.get("/api/memories", headers=_auth(token)).json()) == 2

    async def test_another_user_cannot_list_or_delete_the_memories(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        alice = get_auth_token("alice", "password123")
        bob = get_auth_token("bob", "password456")

        draft = await self._commit(client, alice, monkeypatch)

        assert (
            client.get(
                f"/api/tellings/{draft['id']}/memories", headers=_auth(bob)
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/tellings/{draft['id']}/memories", headers=_auth(bob)
            ).status_code
            == 404
        )


class TestSegmentDates:
    """A resolved date is the cursor's best answer, not the last word."""

    async def test_a_segment_date_can_be_corrected(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        segment_id = draft["segments"][0]["id"]

        response = client.patch(
            f"/api/tellings/{draft['id']}/segments/{segment_id}",
            json={
                "event_date": "1985-07-01T00:00:00",
                "date_precision": "year",
                "date_label": None,
            },
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert response.json()["date_precision"] == "year"

        fetched = client.get(
            f"/api/tellings/{draft['id']}", headers=_auth(token)
        ).json()
        assert fetched["segments"][0]["event_date"].startswith("1985-07-01")

    async def test_an_unknown_date_precision_is_rejected(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        segment_id = draft["segments"][0]["id"]

        response = client.patch(
            f"/api/tellings/{draft['id']}/segments/{segment_id}",
            json={"date_precision": "whenever"},
            headers=_auth(token),
        )

        assert response.status_code == 400


class TestCaptureTelling:
    """Tellings are submitted and come back as a reviewable draft."""

    async def test_capturing_a_typed_telling_proposes_one_segment(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        response = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["raw_transcript"] == TRANSCRIPT
        assert len(body["segments"]) == 1
        assert body["segments"][0]["text"] == TRANSCRIPT

    async def test_a_telling_can_be_fetched_with_its_segments(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        created = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()

        response = client.get(f"/api/tellings/{created['id']}", headers=_auth(token))

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == created["id"]
        assert body["raw_transcript"] == TRANSCRIPT
        assert len(body["segments"]) == 1
        assert body["segments"][0]["ordinal"] == 0

    async def test_a_proposed_segment_carries_structured_content(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        body = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()

        segment = body["segments"][0]
        assert segment["title"].startswith("Structured:")
        assert segment["summary"] == TRANSCRIPT
        assert segment["status"] == "proposed"

    async def test_a_segment_can_be_edited_before_commit(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        body = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        telling_id, segment_id = body["id"], body["segments"][0]["id"]

        response = client.patch(
            f"/api/tellings/{telling_id}/segments/{segment_id}",
            json={
                "text": "Corrected text.",
                "title": "My title",
                "summary": "My summary",
            },
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert response.json()["title"] == "My title"

        fetched = client.get(
            f"/api/tellings/{telling_id}", headers=_auth(token)
        ).json()
        segment = fetched["segments"][0]
        assert segment["text"] == "Corrected text."
        assert segment["title"] == "My title"
        assert segment["summary"] == "My summary"

    async def test_a_segment_can_be_rejected(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        body = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        telling_id, segment_id = body["id"], body["segments"][0]["id"]

        response = client.patch(
            f"/api/tellings/{telling_id}/segments/{segment_id}",
            json={"status": "rejected"},
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    async def test_an_unknown_segment_status_is_rejected(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        body = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        telling_id, segment_id = body["id"], body["segments"][0]["id"]

        response = client.patch(
            f"/api/tellings/{telling_id}/segments/{segment_id}",
            json={"status": "banana"},
            headers=_auth(token),
        )

        assert response.status_code == 400


class TestCommitTelling:
    """Committing turns accepted segments into real memories."""

    async def test_committing_creates_a_memory_linked_to_the_telling(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()

        response = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        )

        assert response.status_code == 200
        committed = response.json()
        assert committed["status"] == "committed"

        memory_id = committed["segments"][0]["memory_id"]
        assert memory_id is not None

        memory = client.get(f"/api/memories/{memory_id}", headers=_auth(token))
        assert memory.status_code == 200
        assert memory.json()["raw_input"] == TRANSCRIPT
        assert memory.json()["title"] == draft["segments"][0]["title"]

    async def test_commit_uses_reviewed_content_and_does_not_re_run_the_agent(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        calls = []

        async def _counting_segmentation(transcript: str):
            calls.append(transcript)
            return SegmentationResult(segments=[
                ProposedSegment(
                    text=transcript,
                    structured=StructuredMemory(
                        title="Agent title",
                        summary=transcript,
                        entities=[],
                        mood="neutral",
                        importance_level=5,
                        initial_tags=["test"],
                    ),
                )
            ])

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", _counting_segmentation
        )

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        assert len(calls) == 1, "structuring should happen once, on the way in"

        segment_id = draft["segments"][0]["id"]
        client.patch(
            f"/api/tellings/{draft['id']}/segments/{segment_id}",
            json={"title": "Reviewed title"},
            headers=_auth(token),
        )

        committed = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        ).json()

        assert len(calls) == 1, "commit must not re-run the Capture Agent"

        memory = client.get(
            f"/api/memories/{committed['segments'][0]['memory_id']}",
            headers=_auth(token),
        ).json()
        assert memory["title"] == "Reviewed title"

    async def test_committed_memories_sync_entities_and_apply_review_flags(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        async def _segmentation(transcript: str):
            return SegmentationResult(segments=[
                ProposedSegment(
                    text=transcript,
                    structured=StructuredMemory(
                        title="Trip to Raleigh",
                        summary=transcript,
                        entities=[EntityData(type="person", value="Dave")],
                        mood="happy",
                        importance_level=7,
                        initial_tags=["trip"],
                        event_date=datetime(1985, 7, 1),
                        date_precision="year",
                    ),
                )
            ])

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", _segmentation
        )

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        committed = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        ).json()

        memory = client.get(
            f"/api/memories/{committed['segments'][0]['memory_id']}",
            headers=_auth(token),
        ).json()
        assert memory["event_date"] is not None
        assert memory["needs_review"] is False

        entities = client.get("/api/entities", headers=_auth(token)).json()
        names = [item["canonical_name"] for item in entities["items"]]
        assert "Dave" in names


class TestDraftIsolation:
    """An unreviewed telling must change nothing observable anywhere else.

    This is the invariant the design rests on. Segments are not ``Memory`` rows
    behind a draft flag, so an uncommitted split cannot appear in the timeline,
    search, review queue or entity graph — and cannot mint entities the user
    would then have to clean up.
    """

    async def _draft(self, client, token, monkeypatch):
        async def _segmentation(transcript: str):
            return SegmentationResult(segments=[
                ProposedSegment(
                    text=transcript,
                    structured=StructuredMemory(
                        title="Trip to Raleigh",
                        summary=transcript,
                        entities=[EntityData(type="person", value="Dave")],
                        mood="happy",
                        importance_level=7,
                        initial_tags=["trip", "raleigh"],
                    ),
                )
            ])

        monkeypatch.setattr(
            "app.routes.tellings.segment_transcript", _segmentation
        )
        response = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        )
        assert response.status_code == 201
        return response.json()

    async def test_a_draft_telling_is_invisible_everywhere(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        await self._draft(client, token, monkeypatch)

        assert client.get("/api/memories", headers=_auth(token)).json() == []
        assert client.get("/api/timeline", headers=_auth(token)).json() == []
        assert client.get("/api/review", headers=_auth(token)).json()["items"] == []
        assert client.get("/api/entities", headers=_auth(token)).json()["items"] == []

        search = client.post(
            "/api/memories/search",
            json={"text": "Raleigh"},
            headers=_auth(token),
        ).json()
        assert search["results"] == []

    async def test_committing_is_what_makes_it_visible(
        self, client, setup_users, get_auth_token, monkeypatch
    ):
        """Guards the test above from passing vacuously."""
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = await self._draft(client, token, monkeypatch)
        client.post(f"/api/tellings/{draft['id']}/commit", headers=_auth(token))

        assert len(client.get("/api/memories", headers=_auth(token)).json()) == 1
        entities = client.get("/api/entities", headers=_auth(token)).json()
        assert [item["canonical_name"] for item in entities["items"]] == ["Dave"]


class TestTellingReviewAndOwnership:
    """Rejection excludes a segment; a telling belongs to one user."""

    async def test_a_rejected_segment_produces_no_memory(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()
        segment_id = draft["segments"][0]["id"]

        client.patch(
            f"/api/tellings/{draft['id']}/segments/{segment_id}",
            json={"status": "rejected"},
            headers=_auth(token),
        )
        committed = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        ).json()

        assert committed["segments"][0]["memory_id"] is None
        assert client.get("/api/memories", headers=_auth(token)).json() == []

    async def test_a_telling_is_visible_only_to_its_owner(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        alice = get_auth_token("alice", "password123")
        bob = get_auth_token("bob", "password456")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(alice),
        ).json()

        assert (
            client.get(f"/api/tellings/{draft['id']}", headers=_auth(bob)).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/tellings/{draft['id']}/commit", headers=_auth(bob)
            ).status_code
            == 404
        )

    async def test_committing_twice_is_refused(
        self, client, setup_users, get_auth_token, fake_segmentation
    ):
        await setup_users()
        token = get_auth_token("alice", "password123")

        draft = client.post(
            "/api/tellings",
            json={"raw_transcript": TRANSCRIPT},
            headers=_auth(token),
        ).json()

        first = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        )
        second = client.post(
            f"/api/tellings/{draft['id']}/commit", headers=_auth(token)
        )

        assert first.status_code == 200
        assert second.status_code == 409
        assert len(client.get("/api/memories", headers=_auth(token)).json()) == 1
