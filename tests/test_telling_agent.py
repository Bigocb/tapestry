"""Tests for the Telling segmentation agent (Issue 29).

Segmentation is a single model pass over the whole transcript. It returns
verbatim span text rather than character offsets, because models miscount
offsets and the transcript on the telling row stays the source of truth.
"""

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

        segments = await segment_transcript(TRANSCRIPT)

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

        segments = await segment_transcript(TRANSCRIPT)
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

        segments = await segment_transcript(TRANSCRIPT)

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

        segments = await segment_transcript(TRANSCRIPT)

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

        segments = await segment_transcript(TRANSCRIPT)

        assert len(segments) == 1
        assert segments[0].text == TRANSCRIPT
