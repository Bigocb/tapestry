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


class TestFuzzyPlaceMatching:
    """Sensor: a generic venue word should not hide the place behind it.

    "Mission Valley Theater" retrieves "Mission Valley Cinemas" only when the
    generic word is dropped and the distinctive part searched on its own. This
    is the limitation met in practice, not a hypothetical.
    """

    @pytest.mark.asyncio
    async def test_the_exact_wording_is_tried_first(self, monkeypatch):
        calls = []

        async def fake_search(name, limit):
            calls.append(name)
            if name == "Mission Valley Theater":
                return []
            return SEARCH_RESPONSE["search"]

        monkeypatch.setattr(lookup, "_search", fake_search)

        match = await lookup.find_place("Mission Valley Theater")

        assert match.label == "Mission Valley Cinemas"
        assert calls[0] == "Mission Valley Theater"
        assert "Mission Valley" in calls

    @pytest.mark.asyncio
    async def test_irrelevant_results_trigger_a_broader_query(self, monkeypatch):
        async def fake_search(name, limit):
            if name == "Mission Valley Theater":
                return [{"id": "Q999", "label": "Something Else Entirely"}]
            return SEARCH_RESPONSE["search"]

        monkeypatch.setattr(lookup, "_search", fake_search)

        matches = await lookup.search_places("Mission Valley Theater")

        assert matches[0].label == "Mission Valley Cinemas"

    @pytest.mark.asyncio
    async def test_a_relevant_direct_hit_is_not_broadened(self, monkeypatch):
        calls = []

        async def fake_search(name, limit):
            calls.append(name)
            return SEARCH_RESPONSE["search"]

        monkeypatch.setattr(lookup, "_search", fake_search)

        await lookup.search_places("Mission Valley Cinemas")

        assert calls == ["Mission Valley Cinemas"]

    @pytest.mark.asyncio
    async def test_a_name_without_a_generic_word_is_queried_as_written(
        self, monkeypatch
    ):
        calls = []

        async def fake_search(name, limit):
            calls.append(name)
            return []

        monkeypatch.setattr(lookup, "_search", fake_search)

        assert await lookup.search_places("Raleigh") == []
        assert calls == ["Raleigh"]

    @pytest.mark.asyncio
    async def test_the_direct_results_survive_when_nothing_better_is_found(
        self, monkeypatch
    ):
        async def fake_search(name, limit):
            if name == "Mission Valley Theater":
                return [{"id": "Q999", "label": "Something Else Entirely"}]
            return []

        monkeypatch.setattr(lookup, "_search", fake_search)

        matches = await lookup.search_places("Mission Valley Theater")

        assert [m.source_id for m in matches] == ["Q999"]


NOMINATIM_RESULT = [
    {
        "osm_type": "node",
        "osm_id": 123456,
        "lat": "39.739236",
        "lon": "-104.990251",
        "name": "1201 Larimer Street",
        "display_name": (
            "1201 Larimer Street, Denver, Colorado, 80204, United States"
        ),
        "type": "house",
    }
]


class TestAddressVerification:
    """Verifying an address is a different question from finding a place.

    A place lookup answers "which place is this?". Verifying an address answers
    "where exactly", and so the answer carries coordinates.
    """

    @pytest.mark.asyncio
    async def test_an_address_resolves_with_coordinates(self, monkeypatch):
        async def fake(query, limit):
            return NOMINATIM_RESULT

        monkeypatch.setattr(lookup, "_nominatim", fake)

        matches = await lookup.address_candidates("1201 Larimer St, Denver")

        assert matches[0].source == "nominatim"
        assert matches[0].latitude == pytest.approx(39.739236)
        assert matches[0].longitude == pytest.approx(-104.990251)
        assert "Larimer" in matches[0].address

    @pytest.mark.asyncio
    async def test_the_full_address_line_is_kept(self, monkeypatch):
        async def fake(query, limit):
            return NOMINATIM_RESULT

        monkeypatch.setattr(lookup, "_nominatim", fake)

        match = (await lookup.address_candidates("1201 Larimer"))[0]

        assert match.address.startswith("1201 Larimer Street")
        assert match.url.startswith("https://www.openstreetmap.org/node/")

    @pytest.mark.asyncio
    async def test_a_blank_query_asks_nobody(self, monkeypatch):
        called = False

        async def fake(query, limit):
            nonlocal called
            called = True
            return NOMINATIM_RESULT

        monkeypatch.setattr(lookup, "_nominatim", fake)

        assert await lookup.address_candidates("   ") == []
        assert called is False

    @pytest.mark.asyncio
    async def test_a_result_without_coordinates_is_ignored(self, monkeypatch):
        async def fake(query, limit):
            return [{"osm_type": "node", "osm_id": 1, "display_name": "Nowhere"}]

        monkeypatch.setattr(lookup, "_nominatim", fake)

        assert await lookup.address_candidates("Nowhere") == []

    def test_requests_are_paced_for_nominatim(self):
        # Their usage policy is at most one request a second, so a burst waits.
        lookup._last_nominatim_call = 100.0
        assert lookup._seconds_until_nominatim_slot(100.2) == pytest.approx(0.8)
        assert lookup._seconds_until_nominatim_slot(101.5) == 0.0
