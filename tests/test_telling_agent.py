"""Tests for the Telling segmentation agent (Issue 29).

Segmentation is a single model pass over the whole transcript. It returns
verbatim span text rather than character offsets, because models miscount
offsets and the transcript on the telling row stays the source of truth.
"""

from datetime import date

import pytest

from app.agents import telling
from app.agents.telling import segment_transcript
from app.models.schemas import StructuredMemory


TRANSCRIPT = (
    "So in the summer of 1985 we drove down to Florida. The next day we went to "
    "Disney. Two years later I started college and met Dave."
)


class TestSegmentTranscript:
    """A transcript becomes an ordered list of proposed segments."""

    @pytest.mark.asyncio
    async def test_returns_ordered_segments_with_verbatim_text(self, monkeypatch):
        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "So in the summer of 1985 we drove down to Florida.",
                        "title": "Trip to Florida",
                        "summary": "We drove to Florida.",
                    },
                    {
                        "text": "The next day we went to Disney.",
                        "title": "Disney",
                        "summary": "We went to Disney.",
                    },
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments

        assert [segment.text for segment in segments] == [
            "So in the summer of 1985 we drove down to Florida.",
            "The next day we went to Disney.",
        ]
        assert [segment.structured.title for segment in segments] == [
            "Trip to Florida",
            "Disney",
        ]

    @pytest.mark.asyncio
    async def test_normalises_segment_fields(self, monkeypatch):
        """Segments go through the same validation single capture uses."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "We drove to Florida.",
                        "title": "",
                        "summary": "We drove to Florida.",
                        "entities": [
                            {"type": "person", "value": "Dave"},
                            {"type": "wizard", "value": "nonsense"},
                        ],
                        "mood": "happy",
                        "importance_level": 99,
                        "initial_tags": ["trip"],
                    }
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments
        structured = segments[0].structured

        assert structured.importance_level == 10
        assert [entity.type for entity in structured.entities] == ["person"]
        assert structured.title.strip()

    @pytest.mark.asyncio
    async def test_drops_unusable_segments_keeping_the_rest_in_order(
        self, monkeypatch
    ):
        """A malformed item must not become an empty memory."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {"text": "First memory.", "title": "First"},
                    {"text": "   ", "title": "Whitespace only"},
                    {"title": "No text at all"},
                    "not even an object",
                    {"text": "Third memory.", "title": "Third"},
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments

        assert [segment.text for segment in segments] == [
            "First memory.",
            "Third memory.",
        ]

    @pytest.mark.asyncio
    async def test_falls_back_to_one_segment_when_the_model_fails(
        self, monkeypatch
    ):
        """A model outage degrades to a reviewable memory, never to nothing."""

        async def failing_chat(prompt, system_prompt=None):
            raise RuntimeError("ollama unavailable")

        async def fake_structure(raw_input: str) -> StructuredMemory:
            return StructuredMemory(
                title="Structured: " + raw_input[:40],
                summary=raw_input,
                entities=[],
                importance_level=5,
                initial_tags=[],
            )

        monkeypatch.setattr(telling, "_call_ollama_chat", failing_chat)
        monkeypatch.setattr(telling, "structure_memory", fake_structure)

        segments = (await segment_transcript(TRANSCRIPT)).segments

        assert len(segments) == 1
        assert segments[0].text == TRANSCRIPT
        assert segments[0].structured.summary == TRANSCRIPT

    @pytest.mark.asyncio
    async def test_falls_back_when_no_segment_is_usable(self, monkeypatch):
        """A response full of junk must not silently produce zero memories."""

        async def junk_chat(prompt, system_prompt=None):
            return {"segments": [{"text": "   "}, {"title": "no text"}, 42]}

        async def fake_structure(raw_input: str) -> StructuredMemory:
            return StructuredMemory(
                title="Structured: " + raw_input[:40],
                summary=raw_input,
                entities=[],
                importance_level=5,
                initial_tags=[],
            )

        monkeypatch.setattr(telling, "_call_ollama_chat", junk_chat)
        monkeypatch.setattr(telling, "structure_memory", fake_structure)

        segments = (await segment_transcript(TRANSCRIPT)).segments

        assert len(segments) == 1
        assert segments[0].text == TRANSCRIPT

    @pytest.mark.asyncio
    async def test_explicit_null_date_is_not_re_derived(self, monkeypatch):
        """A year mentioned in passing must not date the memory.

        The deterministic scan in _build_structured_memory re-derives a date
        from any year-like phrase. "the DJ played early 2000s throwbacks" says
        when the music was from, not when the memory happened, so the model's
        explicit "no date" has to win over that scan.
        """

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "the DJ played nothing but cheesy early 2000s throwbacks",
                        "title": "The welcome dance",
                        "event_date": None,
                        "date_precision": None,
                        "date_label": None,
                    }
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments
        structured = segments[0].structured

        assert structured.event_date is None
        assert structured.date_precision == "unknown"
        assert structured.date_label is None

    @pytest.mark.asyncio
    async def test_drops_an_exact_date_whose_year_is_absent_from_the_text(
        self, monkeypatch
    ):
        """"August 15th" has no year; answering 1900-08-15 invents one.

        An invented year is worse than no date, because it silently files the
        memory in the wrong century.
        """

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "it was August 15th when it started",
                        "title": "First day",
                        "event_date": "1900-08-15T00:00:00",
                        "date_precision": "exact",
                        "date_label": None,
                    }
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments
        structured = segments[0].structured

        assert structured.event_date is None
        assert structured.date_precision == "unknown"

    @pytest.mark.asyncio
    async def test_keeps_an_exact_date_whose_year_is_in_the_text(self, monkeypatch):
        """The guard must not throw away dates the account actually states."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "In July 1985 we drove down to Florida.",
                        "title": "Florida",
                        "event_date": "1985-07-01T00:00:00",
                        "date_precision": "exact",
                        "date_label": None,
                    }
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments
        structured = segments[0].structured

        assert structured.event_date is not None
        assert structured.event_date.year == 1985

    @pytest.mark.asyncio
    async def test_segments_get_dates_from_the_story_cursor(self, monkeypatch):
        """A segment with no date of its own is anchored by the one before it."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {
                        "text": "On July 29, 1976 I was born in Conway.",
                        "title": "Born in Conway",
                        "event_date": "1976-07-29T00:00:00",
                        "date_precision": "exact",
                        "date_label": None,
                    },
                    {
                        "text": "The next day my grandmother arrived.",
                        "title": "Grandmother arrives",
                        "event_date": None,
                        "date_precision": None,
                        "date_label": None,
                    },
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        segments = (await segment_transcript(TRANSCRIPT)).segments

        assert segments[0].structured.event_date.date() == date(1976, 7, 29)
        assert segments[1].structured.event_date.date() == date(1976, 7, 30)

    @pytest.mark.asyncio
    async def test_returns_the_telling_frame_alongside_its_segments(
        self, monkeypatch
    ):
        """The period the account is about belongs to the telling, not a segment."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {"text": "First memory.", "title": "One", "date_label": "high school"},
                    {"text": "Second memory.", "title": "Two", "date_label": "high school"},
                    {"text": "Third memory.", "title": "Three", "date_label": "high school"},
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        result = await segment_transcript(TRANSCRIPT)

        assert [segment.text for segment in result.segments] == [
            "First memory.",
            "Second memory.",
            "Third memory.",
        ]
        assert result.frame_label == "high school"

    @pytest.mark.asyncio
    async def test_an_undated_segment_inherits_the_frame(self, monkeypatch):
        """What the account is about rescues a memory that never says when."""

        async def fake_chat(prompt, system_prompt=None):
            return {
                "segments": [
                    {"text": "First memory.", "title": "One", "date_label": "high school"},
                    {
                        "text": "Second memory.",
                        "title": "Two",
                        "event_date": None,
                        "date_precision": None,
                        "date_label": None,
                    },
                ]
            }

        monkeypatch.setattr(telling, "_call_ollama_chat", fake_chat)

        result = await segment_transcript(TRANSCRIPT)

        assert result.segments[1].structured.date_label == "high school"
        assert result.segments[1].structured.event_date is None
