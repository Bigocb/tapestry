"""Tests for the Enrichment Agent."""

import uuid

import pytest

from app.agents.enrichment import (
    ENRICHMENT_SYSTEM_PROMPT,
    _build_enrichment_prompt,
    _parse_related_memory_ids,
    _sanitize_enrichment_output,
    _validate_uuid,
    enrich_memory,
)
from app.models.schemas import EntityData, StructuredMemory


class TestEnrichmentHelpers:
    """Unit tests for internal enrichment helper functions."""

    def test_validate_uuid_accepts_string_and_uuid(self):
        from uuid import uuid4, UUID

        u = uuid4()
        assert _validate_uuid(u) == str(u)
        assert _validate_uuid(str(u)) == str(u)

    def test_validate_uuid_rejects_invalid(self):
        assert _validate_uuid("not-a-uuid") is None
        assert _validate_uuid(None) is None

    def test_build_enrichment_prompt_contains_memory_and_context(self):
        memory = {"title": "Lunch with Sarah"}
        similar = [{"memory_id": str(uuid.uuid4()), "title": "Project review"}]
        prompt = _build_enrichment_prompt(memory, similar)
        assert "Lunch with Sarah" in prompt
        assert "Project review" in prompt

    def test_parse_related_memory_ids_filters_invalid(self):
        valid_id = str(uuid.uuid4())
        invalid_id = str(uuid.uuid4())
        result = _parse_related_memory_ids(
            {"related_memory_ids": [valid_id, invalid_id, "bad-id"]},
            {valid_id},
        )
        assert result == [valid_id]

    def test_sanitize_enrichment_output_uses_fallback_values(self):
        current = StructuredMemory(
            title="Current title",
            summary="Current summary.",
            entities=[EntityData(type="person", value="Sarah")],
            mood="happy",
            importance_level=6,
            initial_tags=["current"],
        )
        result = _sanitize_enrichment_output({}, current, set())
        assert result.title == "Current title"
        assert result.summary == "Current summary."
        assert result.mood == "happy"
        assert result.importance_level == 6
        assert result.initial_tags == ["current"]

    def test_sanitize_enrichment_output_clamps_importance(self):
        current = StructuredMemory(title="t", summary="s")
        result = _sanitize_enrichment_output({"importance_level": 99}, current, set())
        assert result.importance_level == 10


class TestEnrichMemory:
    """Integration-ish tests for enrich_memory with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_enrich_memory_suggests_tags_and_links(self, monkeypatch):
        memory_id = str(uuid.uuid4())
        memory = {
            "title": "Lunch with Sarah",
            "summary": "Lunch with Sarah at the cafe.",
            "entities": [{"type": "person", "value": "Sarah"}],
            "mood": "happy",
            "importance_level": 5,
            "initial_tags": ["lunch"],
        }
        related_id = str(uuid.uuid4())
        similar = [
            {
                "memory_id": related_id,
                "title": "Previous lunch with Sarah",
                "summary": "We had lunch last week too.",
                "score": 0.85,
            },
            {
                "memory_id": str(uuid.uuid4()),
                "title": "Random unrelated memory",
                "summary": "Something else entirely.",
                "score": 0.2,
            },
        ]

        async def fake_call(messages: list) -> dict:
            assert messages[0]["content"] == ENRICHMENT_SYSTEM_PROMPT
            return {
                "title": "Lunch with Sarah",
                "summary": "Lunch with Sarah at the cafe.",
                "entities": [{"type": "person", "value": "Sarah"}],
                "mood": "happy",
                "importance_level": 6,
                "initial_tags": ["lunch", "friends", "cafe"],
                "related_memory_ids": [related_id],
            }

        monkeypatch.setattr("app.agents.enrichment._call_ollama_chat", fake_call)

        result, related_ids = await enrich_memory(memory, similar)

        assert isinstance(result, StructuredMemory)
        assert result.importance_level == 6
        assert set(result.initial_tags) == {"lunch", "friends", "cafe"}
        assert related_ids == [related_id]

    @pytest.mark.asyncio
    async def test_enrich_memory_falls_back_on_llm_error(self, monkeypatch):
        async def failing_call(messages: list) -> dict:
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr("app.agents.enrichment._call_ollama_chat", failing_call)

        memory = {
            "title": "Fallback title",
            "summary": "Fallback summary.",
            "entities": [],
            "mood": "neutral",
            "importance_level": 5,
            "initial_tags": ["fallback"],
        }
        result, related_ids = await enrich_memory(memory, [])

        assert result.title == "Fallback title"
        assert result.initial_tags == ["fallback"]
        assert related_ids == []
