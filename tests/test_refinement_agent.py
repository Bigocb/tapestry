"""Tests for the Refinement Agent."""

import pytest

from app.agents.refinement import (
    REFINEMENT_SYSTEM_PROMPT,
    _build_structured_memory,
    _normalize_entities,
    _structured_memory_from_dict,
    refine_memory,
)
from app.models.schemas import EntityData, StructuredMemory


class TestRefinementAgentHelpers:
    """Unit tests for internal helper functions."""

    def test_structured_memory_from_dict_parses_valid_data(self):
        data = {
            "title": "Project review",
            "summary": "Reviewed project progress with Sarah.",
            "entities": [
                {"type": "person", "value": "Sarah", "metadata": {"role": "manager"}}
            ],
            "mood": "focused",
            "importance_level": 8,
            "initial_tags": ["work", "review"],
        }
        result = _structured_memory_from_dict(data)
        assert result.title == "Project review"
        assert result.summary == "Reviewed project progress with Sarah."
        assert result.entities == [EntityData(type="person", value="Sarah", metadata={"role": "manager"})]
        assert result.mood == "focused"
        assert result.importance_level == 8
        assert result.initial_tags == ["work", "review"]

    def test_structured_memory_from_dict_handles_non_dict(self):
        result = _structured_memory_from_dict(None)
        assert result.title == "Untitled"
        assert result.summary == "No summary available"
        assert result.entities == []
        assert result.mood is None
        assert result.importance_level == 5
        assert result.initial_tags == []

    def test_build_structured_memory_uses_fallback_fields(self):
        fallback = StructuredMemory(
            title="Fallback title",
            summary="Fallback summary",
            entities=[EntityData(type="concept", value="fallback")],
            mood="neutral",
            importance_level=4,
            initial_tags=["fallback"],
        )
        raw_dict = {}
        result = _build_structured_memory(raw_dict, fallback)
        assert result.title == fallback.title
        assert result.summary == fallback.summary
        assert result.entities == fallback.entities
        assert result.mood == fallback.mood
        assert result.importance_level == fallback.importance_level
        assert result.initial_tags == fallback.initial_tags

    def test_build_structured_memory_clamps_importance(self):
        fallback = StructuredMemory(title="t", summary="s")
        result = _build_structured_memory({"importance_level": 0}, fallback)
        assert result.importance_level == 1

        result = _build_structured_memory({"importance_level": 15}, fallback)
        assert result.importance_level == 10

    def test_normalize_entities_skips_invalid(self):
        raw = [
            {"type": "event", "value": "Q3 planning"},
            {"type": "unknown", "value": "x"},
            {"value": "no type"},
        ]
        result = _normalize_entities(raw)
        assert result == [EntityData(type="event", value="Q3 planning", metadata=None)]


class TestRefineMemory:
    """Integration-ish tests for refine_memory with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_refine_memory_resolves_ambiguity(self, monkeypatch):
        raw_input = "That meeting with Sarah went really well."
        structured_content = {
            "title": "Meeting with Sarah",
            "summary": "A meeting with Sarah went well.",
            "entities": [{"type": "person", "value": "Sarah"}],
            "mood": "happy",
            "importance_level": 6,
            "initial_tags": ["work"],
        }
        recent_memories = [
            {
                "title": "Q3 planning session",
                "summary": "Planning session for Q3 with Sarah on 2024-07-15.",
                "entities": [{"type": "date", "value": "2024-07-15"}],
            }
        ]

        async def fake_call(messages: list) -> dict:
            assert messages[0]["content"] == REFINEMENT_SYSTEM_PROMPT
            return {
                "title": "Q3 planning meeting with Sarah",
                "summary": "The Q3 planning meeting with Sarah on 2024-07-15 went really well.",
                "entities": [
                    {"type": "person", "value": "Sarah"},
                    {"type": "event", "value": "Q3 planning meeting", "metadata": {"date": "2024-07-15"}},
                ],
                "mood": "happy",
                "importance_level": 7,
                "initial_tags": ["work", "planning"],
            }

        monkeypatch.setattr("app.agents.refinement._call_ollama_chat", fake_call)

        result = await refine_memory(raw_input, structured_content, recent_memories)

        assert isinstance(result, StructuredMemory)
        assert "Q3 planning" in result.title
        assert "2024-07-15" in result.summary
        assert any(e.value == "Q3 planning meeting" and e.type == "event" for e in result.entities)
        assert result.importance_level == 7

    @pytest.mark.asyncio
    async def test_refine_memory_falls_back_on_llm_error(self, monkeypatch):
        async def failing_call(messages: list) -> dict:
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr("app.agents.refinement._call_ollama_chat", failing_call)

        structured_content = {
            "title": "Original title",
            "summary": "Original summary.",
            "entities": [],
            "mood": "calm",
            "importance_level": 5,
            "initial_tags": ["original"],
        }
        result = await refine_memory("some raw input", structured_content, [])

        assert isinstance(result, StructuredMemory)
        assert result.title == "Original title"
        assert result.summary == "Original summary."
        assert result.mood == "calm"
        assert result.importance_level == 5
        assert result.initial_tags == ["original"]

    @pytest.mark.asyncio
    async def test_refine_memory_returns_fallback_for_empty_input(self):
        result = await refine_memory("", {"title": "Empty", "summary": "Empty"}, [])
        assert result.title == "Empty"
