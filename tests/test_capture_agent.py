"""Tests for the Capture Agent."""

import pytest

from app.agents.capture import (
    CAPTURE_SYSTEM_PROMPT,
    _build_structured_memory,
    _fallback_structured_memory,
    _normalize_entities,
    structure_memory,
)
from app.models.schemas import EntityData, StructuredMemory


class TestCaptureAgentHelpers:
    """Unit tests for internal helper functions."""

    def test_fallback_structured_memory_uses_input(self):
        raw = "Just a quick thought about the project deadline."
        result = _fallback_structured_memory(raw)

        assert isinstance(result, StructuredMemory)
        assert result.title == raw
        assert result.summary == raw
        assert result.entities == []
        assert result.mood is None
        assert result.importance_level == 5
        assert isinstance(result.initial_tags, list)
        assert len(result.initial_tags) > 0
        assert all(isinstance(tag, str) for tag in result.initial_tags)

    def test_fallback_structured_memory_truncates_long_title(self):
        raw = "x" * 200
        result = _fallback_structured_memory(raw)
        assert result.title == "x" * 97 + "..."
        assert result.summary == raw

    def test_normalize_entities_filters_invalid_types(self):
        raw = [
            {"type": "person", "value": "Sarah"},
            {"type": "invalid", "value": "foo"},
            {"type": "place", "value": ""},
            "not-a-dict",
        ]
        result = _normalize_entities(raw)
        assert result == [EntityData(type="person", value="Sarah", metadata=None)]

    def test_normalize_entities_preserves_metadata(self):
        raw = [{"type": "date", "value": "last Tuesday", "metadata": {"format": "relative"}}]
        result = _normalize_entities(raw)
        assert result[0].metadata == {"format": "relative"}

    def test_build_structured_memory_sanitizes_fields(self):
        raw_dict = {
            "title": "Coffee with Sarah",
            "summary": "Met Sarah at the downtown cafe to discuss her new role.",
            "entities": [
                {"type": "person", "value": "Sarah"},
                {"type": "place", "value": "downtown cafe"},
            ],
            "mood": "excited",
            "importance_level": 7,
            "initial_tags": ["work", "career", "coffee"],
        }
        raw_input = "Met Sarah downtown to talk about her role."

        result = _build_structured_memory(raw_dict, raw_input)

        assert result.title == "Coffee with Sarah"
        assert result.summary == "Met Sarah at the downtown cafe to discuss her new role."
        assert result.mood == "excited"
        assert result.importance_level == 7
        assert len(result.entities) == 2
        assert result.initial_tags == ["work", "career", "coffee"]

    def test_build_structured_memory_uses_fallback_for_missing_title(self):
        raw_dict = {"summary": "Some summary"}
        raw_input = "x" * 150
        result = _build_structured_memory(raw_dict, raw_input)
        assert result.title == raw_input[:97] + "..."

    def test_build_structured_memory_clamps_importance(self):
        raw_dict = {"importance_level": 99}
        raw_input = "test"
        result = _build_structured_memory(raw_dict, raw_input)
        assert result.importance_level == 10

    def test_build_structured_memory_defaults_importance(self):
        raw_dict = {}
        raw_input = "test"
        result = _build_structured_memory(raw_dict, raw_input)
        assert result.importance_level == 5


class TestCaptureAgentStructureMemory:
    """Integration-ish tests for structure_memory with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_structure_memory_returns_llm_output(self, monkeypatch):
        raw_input = "Had lunch with Sarah and Mike at the riverfront cafe, great conversation about work."

        async def fake_call(prompt: str) -> dict:
            assert CAPTURE_SYSTEM_PROMPT in prompt or "Structure the following" in prompt
            return {
                "title": "Lunch with Sarah and Mike",
                "summary": "Lunch at the riverfront cafe with Sarah and Mike discussing work.",
                "entities": [
                    {"type": "person", "value": "Sarah"},
                    {"type": "person", "value": "Mike"},
                    {"type": "place", "value": "riverfront cafe"},
                ],
                "mood": "happy",
                "importance_level": 6,
                "initial_tags": ["lunch", "work", "friends"],
            }

        monkeypatch.setattr(
            "app.agents.capture._call_ollama_chat", fake_call
        )

        result = await structure_memory(raw_input)

        assert isinstance(result, StructuredMemory)
        assert result.title == "Lunch with Sarah and Mike"
        assert result.mood == "happy"
        assert result.importance_level == 6
        assert len(result.entities) == 3
        assert "work" in result.initial_tags

    @pytest.mark.asyncio
    async def test_structure_memory_falls_back_on_llm_error(self, monkeypatch):
        async def failing_call(prompt: str) -> dict:
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr("app.agents.capture._call_ollama_chat", failing_call)

        raw_input = "A rambling memory that the LLM fails to structure."
        result = await structure_memory(raw_input)

        assert isinstance(result, StructuredMemory)
        assert result.title == raw_input
        assert result.summary == raw_input
        assert result.entities == []
