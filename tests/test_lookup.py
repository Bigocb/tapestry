"""Tests for looking a place up in the outside world (Issue 38).

Enrichment has meant "from the user's other memories" until now. This is the
other direction, and the thing that makes it different is provenance: a
looked-up fact must never be mistaken for something the user said.
"""

import pytest

from app import lookup


SEARCH_RESPONSE = {
    "search": [
        {
            "id": "Q43096397",
            "label": "Mission Valley Cinemas",
            "description": (
                "movie theater in Raleigh, North Carolina, United States"
            ),
            "concepturi": "http://www.wikidata.org/entity/Q43096397",
        }
    ]
}


class TestFindPlace:
    @pytest.mark.asyncio
    async def test_the_match_carries_its_source_and_wording(self, monkeypatch):
        async def fake_search(name, limit):
            return SEARCH_RESPONSE["search"]

        monkeypatch.setattr(lookup, "_search", fake_search)

        match = await lookup.find_place("Mission Valley Theater")

        # What it matched is the point: without this a wrong match is silent.
        assert match.source == "wikidata"
        assert match.source_id == "Q43096397"
        assert match.label == "Mission Valley Cinemas"
        assert "movie theater in Raleigh" in match.description
        assert match.url.endswith("Q43096397")

    @pytest.mark.asyncio
    async def test_nothing_found_returns_nothing(self, monkeypatch):
        async def fake_search(name, limit):
            return []

        monkeypatch.setattr(lookup, "_search", fake_search)

        assert await lookup.find_place("A Place That Never Was") is None

    @pytest.mark.asyncio
    async def test_a_result_with_no_id_is_ignored(self, monkeypatch):
        async def fake_search(name, limit):
            # Wikidata occasionally returns entries without the fields we need.
            return [{"label": "Something", "description": None}]

        monkeypatch.setattr(lookup, "_search", fake_search)

        assert await lookup.find_place("Something") is None

    @pytest.mark.asyncio
    async def test_a_missing_description_is_allowed(self, monkeypatch):
        async def fake_search(name, limit):
            return [{"id": "Q1", "label": "A Place"}]

        monkeypatch.setattr(lookup, "_search", fake_search)

        match = await lookup.find_place("A Place")

        assert match.label == "A Place"
        assert match.description is None
