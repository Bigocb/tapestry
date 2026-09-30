"""Tests for the telling date cursor (Issue 30).

A telling's dates anchor to the memories around them, not to the moment of
capture. "The next day" means the day after the memory before it — never
tomorrow — and a year stated once may govern several memories that follow.
"""

from datetime import datetime, timezone

from app.agents.telling_dates import resolve_telling_dates


class TestResolveTellingDates:
    """The cursor threads through the segments in narrative order."""

    def test_the_next_day_resolves_from_the_preceding_memory(self):
        dates = resolve_telling_dates(
            [
                "On July 29, 1976 I was born in Conway, South Carolina.",
                "The next day my grandmother arrived.",
            ]
        )

        assert dates[0].event_date == datetime(1976, 7, 29, tzinfo=timezone.utc)
        assert dates[1].event_date == datetime(1976, 7, 30, tzinfo=timezone.utc)

    def test_the_cursor_keeps_advancing_across_later_segments(self):
        dates = resolve_telling_dates(
            [
                "On July 29, 1976 I was born in Conway.",
                "The next day my grandmother arrived.",
                "Two days later we went home.",
            ]
        )

        assert dates[2].event_date == datetime(1976, 8, 1, tzinfo=timezone.utc)

    def test_precision_coarsens_but_never_sharpens(self):
        # A year plus years is still a year.
        coarse = resolve_telling_dates(
            [
                "Back in 1985 we drove to Florida.",
                "Two years later I started college.",
            ]
        )
        assert coarse[0].precision == "year"
        assert coarse[1].precision == "year"
        assert coarse[1].event_date.year == 1987

        # A precise day plus a span of years can no longer claim to be a day.
        fine = resolve_telling_dates(
            [
                "On July 29, 1976 I was born.",
                "Five years later we moved to Raleigh.",
            ]
        )
        assert fine[1].event_date == datetime(1981, 7, 29, tzinfo=timezone.utc)
        assert fine[1].precision == "year"

    def test_backwards_references_work(self):
        dates = resolve_telling_dates(
            [
                "On July 29, 1976 I was born in Conway.",
                "The week before, my parents had moved there.",
                "Two days before that, the car broke down.",
            ]
        )

        assert dates[1].event_date == datetime(1976, 7, 22, tzinfo=timezone.utc)
        assert dates[2].event_date == datetime(1976, 7, 20, tzinfo=timezone.utc)

    def test_a_stated_date_re_anchors_what_follows(self):
        """The leap in time that makes a non-linear account work."""

        dates = resolve_telling_dates(
            [
                "On July 29, 1976 I was born.",
                "The next day my grandmother arrived.",
                "Then in 1994 I saw the Grateful Dead.",
                "The next day I drove home.",
            ]
        )

        assert dates[1].event_date == datetime(1976, 7, 30, tzinfo=timezone.utc)
        assert dates[2].event_date == datetime(1994, 1, 1, tzinfo=timezone.utc)
        assert dates[3].event_date == datetime(1994, 1, 2, tzinfo=timezone.utc)

    def test_a_relative_phrase_with_no_anchor_stays_undated(self):
        dates = resolve_telling_dates(["The next day we went to Disney."])

        assert dates[0].event_date is None
        assert dates[0].precision == "unknown"
