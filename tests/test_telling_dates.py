"""Tests for the telling date cursor (Issue 30).

A telling's dates anchor to the memories around them, not to the moment of
capture. "The next day" means the day after the memory before it — never
tomorrow — and a year stated once may govern several memories that follow.
"""

from datetime import datetime, timezone

from app.agents.capture import ResolvedDate
from app.agents.telling_dates import (
    derive_frame,
    inherit_frame,
    resolve_telling_dates,
)


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

    def test_a_relative_phrase_wins_over_a_guessed_date(self):
        """"The next day" is the cursor's to resolve, not the segmenter's.

        A segmenter seeing only this span cannot know what it follows, so it
        tends to answer with the month it can see. The cursor can do better.
        """
        dates = resolve_telling_dates(
            [
                "In August 2003 I started high school.",
                "The next day my grandmother arrived.",
            ],
            known=[
                ResolvedDate(event_date=datetime(2003, 8, 1), precision="month"),
                ResolvedDate(event_date=datetime(2003, 8, 1), precision="month"),
            ],
        )

        assert dates[1].event_date == datetime(2003, 8, 2)

    def test_a_label_is_dropped_once_the_shift_leaves_its_period(self):
        """Wording that described the anchor must not describe a later date."""
        august = ResolvedDate(
            event_date=datetime(2003, 8, 1), precision="month", label="August 2003"
        )

        dates = resolve_telling_dates(
            [
                "In August 2003 I started high school.",
                "The next day my grandmother arrived.",
                "Two years later I got my own car.",
            ],
            known=[august, None, None],
        )

        # A day later is still in August 2003, so the wording still holds.
        assert dates[1].label == "August 2003"
        # Two years later it describes nothing true.
        assert dates[2].label is None


class TestTellingFrame:
    """The period a telling as a whole is about."""

    def test_the_frame_is_the_label_most_segments_share(self):
        frame = derive_frame(
            [
                ResolvedDate(label="first month in high school"),
                ResolvedDate(label="first month in high school"),
                ResolvedDate(label="the welcome dance"),
            ]
        )

        assert frame.label == "first month in high school"

    def test_undated_segments_inherit_the_frame(self):
        frame = derive_frame(
            [
                ResolvedDate(label="first month in high school"),
                ResolvedDate(label="first month in high school"),
            ]
        )

        dates = inherit_frame(
            [
                ResolvedDate(
                    event_date=datetime(2003, 8, 1),
                    precision="month",
                    label="first month in high school",
                ),
                # Nothing at all: no date, no wording of its own.
                ResolvedDate(),
            ],
            frame,
        )

        assert dates[1].label == "first month in high school"
        # The frame supplies a period, not a date.
        assert dates[1].event_date is None

    def test_a_segment_with_its_own_signal_is_left_alone(self):
        frame = derive_frame(
            [ResolvedDate(label="high school"), ResolvedDate(label="high school")]
        )

        dates = inherit_frame(
            [
                ResolvedDate(event_date=datetime(1994, 7, 1), precision="exact"),
                ResolvedDate(label="the wedding", precision="unknown"),
            ],
            frame,
        )

        assert dates[0].label is None
        assert dates[0].event_date == datetime(1994, 7, 1)
        assert dates[1].label == "the wedding"

    def test_no_shared_label_means_no_frame(self):
        frame = derive_frame([ResolvedDate(), ResolvedDate()])
        assert frame.label is None

        # With no frame there is nothing to inherit, and the segment stays
        # honestly undated — which is what puts it in the review queue.
        dates = inherit_frame([ResolvedDate()], frame)
        assert dates[0].label is None
        assert dates[0].event_date is None
