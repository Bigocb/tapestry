"""Tests for the Search Agent."""

import pytest

from app.agents.search import (
    SEARCH_SYSTEM_PROMPT,
    _build_search_query,
    _heuristic_parse,
    _parse_iso_datetime,
    parse_search_query,
)
from app.models.schemas import SearchFilters, SearchQuery


class TestSearchAgentHelpers:
    """Unit tests for internal search parsing helpers."""

    def test_build_search_query_parses_all_fields(self):
        raw = {
            "text": "manager conversations",
            "semantic": "discussions with my manager about career",
            "filters": {
                "date_range_start": "2024-01-01T00:00:00Z",
                "date_range_end": "2024-03-31T23:59:59Z",
                "tags": ["work", "career"],
                "mood": "focused",
                "importance_min": 5,
                "importance_max": 10,
            },
            "limit": 10,
            "offset": 0,
        }
        result = _build_search_query(raw)
        assert result.text == "manager conversations"
        assert result.semantic == "discussions with my manager about career"
        assert result.limit == 10
        assert result.offset == 0
        assert result.filters.tags == ["work", "career"]
        assert result.filters.mood == "focused"
        assert result.filters.importance_min == 5
        assert result.filters.importance_max == 10

    def test_build_search_query_clamps_limit(self):
        raw = {"limit": 500, "offset": -5}
        result = _build_search_query(raw)
        assert result.limit == 100
        assert result.offset == 0

    def test_build_search_query_handles_empty_text(self):
        raw = {"text": "   "}
        result = _build_search_query(raw)
        assert result.text is None

    def test_parse_iso_datetime_returns_none_for_invalid(self):
        assert _parse_iso_datetime("not-a-date") is None
        assert _parse_iso_datetime(None) is None

    def test_heuristic_parse_handles_q1(self):
        result = _heuristic_parse("manager conversations in Q1")
        assert "q1" in result.text.lower()
        assert result.filters.date_range_start is not None
        assert result.filters.date_range_end is not None
        assert result.semantic == "manager conversations in Q1"

    def test_heuristic_parse_handles_this_week(self):
        result = _heuristic_parse("meetings this week")
        assert result.filters.date_range_start is not None
        assert result.filters.date_range_end is not None

    def test_heuristic_parse_handles_last_month(self):
        result = _heuristic_parse("memories from last month")
        assert result.filters.date_range_start is not None
        assert result.filters.date_range_end is not None
        assert "last month" in result.text.lower()


class TestParseSearchQuery:
    """Integration-ish tests for parse_search_query with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_parse_search_query_returns_llm_output(self, monkeypatch):
        async def fake_call(messages: list) -> dict:
            assert messages[0]["content"] == SEARCH_SYSTEM_PROMPT
            return {
                "text": "manager",
                "semantic": "career conversations with manager",
                "filters": {
                    "date_range_start": "2024-01-01T00:00:00Z",
                    "date_range_end": "2024-03-31T23:59:59Z",
                    "tags": ["work"],
                    "mood": "focused",
                    "importance_min": 5,
                },
                "limit": 15,
                "offset": 0,
            }

        monkeypatch.setattr("app.agents.search._call_ollama_chat", fake_call)
        result = await parse_search_query("Tell me about my manager conversations in Q1")

        assert isinstance(result, SearchQuery)
        assert result.text == "manager"
        assert result.semantic == "career conversations with manager"
        assert result.filters.tags == ["work"]
        assert result.limit == 15

    @pytest.mark.asyncio
    async def test_parse_search_query_falls_back_on_error(self, monkeypatch):
        async def failing_call(messages: list) -> dict:
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr("app.agents.search._call_ollama_chat", failing_call)
        result = await parse_search_query("coffee with Sarah last week")

        assert isinstance(result, SearchQuery)
        assert "coffee" in result.text.lower()
        assert "sarah" in result.text.lower()

    @pytest.mark.asyncio
    async def test_parse_search_query_handles_empty_input(self):
        result = await parse_search_query("")
        assert result.text is None
        assert result.semantic is None
