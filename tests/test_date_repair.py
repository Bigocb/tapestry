"""Tests for the one-off date-metadata repair.

The label is the strongest evidence a memory carries about its own date; failing
that, a fuzzy period read out of the raw text. Nothing else is written back, so
a bare day scraped out of prose never overrules the row.
"""

from datetime import datetime

from scripts.repair_date_metadata import label_period, propose


class TestLabelPeriod:
    def test_a_bare_year_is_a_year(self):
        assert label_period("1988") == ("year", datetime(1988, 1, 1), None)

    def test_a_month_and_year_is_a_month(self):
        assert label_period("September 2000") == ("month", datetime(2000, 9, 1), None)

    def test_a_written_day_is_exact(self):
        assert label_period("September 29, 1997") == (
            "exact",
            datetime(1997, 9, 29),
            None,
        )

    def test_a_slash_date_is_exact(self):
        assert label_period("2/18/1999") == ("exact", datetime(1999, 2, 18), None)

    def test_a_year_range_is_a_range(self):
        assert label_period("1987-1990") == (
            "range",
            datetime(1987, 1, 1),
            datetime(1990, 12, 31),
        )

    def test_a_qualified_decade_is_the_decade(self):
        assert label_period("early 1980s") == (
            "decade",
            datetime(1980, 1, 1),
            datetime(1989, 12, 31),
        )

    def test_a_name_is_not_a_period(self):
        assert label_period("Middle school") is None
        assert label_period("") is None


class TestPropose:
    def test_a_year_label_corrects_a_range_precision(self):
        assert propose("1985", "range", datetime(1985, 1, 1), None) == (
            "year",
            datetime(1985, 1, 1),
            None,
            None,
        )

    def test_a_month_label_fills_in_a_missing_date(self):
        assert propose("September 2000", "range", None, None) == (
            "month",
            datetime(2000, 9, 1),
            None,
            None,
        )

    def test_a_month_label_keeps_a_real_day_that_agrees(self):
        # "May 1992" stored with the day 6 — a real day, not a placeholder.
        assert propose("May 1992", "exact", datetime(1992, 5, 6), None) == (
            "exact",
            datetime(1992, 5, 6),
            None,
            None,
        )

    def test_a_month_label_ignores_a_day_in_the_wrong_month(self):
        # "May 1991" stored as 20 March — the label is what we trust.
        assert propose("May 1991", "month", datetime(1991, 3, 20), None) == (
            "month",
            datetime(1991, 5, 1),
            None,
            None,
        )

    def test_a_decade_that_is_already_stored_is_left_as_it_is(self):
        # "early 1980s" stores 1980-1983; a plain decade end would widen it.
        assert propose(
            "early 1980s",
            "decade",
            datetime(1980, 1, 1),
            datetime(1983, 12, 30),
        ) == ("decade", datetime(1980, 1, 1), datetime(1983, 12, 30), None)

    def test_a_row_with_no_usable_label_is_left_alone(self):
        # Nothing is read out of the raw text: prose mentions periods for other
        # reasons ("Ryan's 70s Dodge Dart"), and re-reading it moved rows to the
        # wrong decade.
        assert propose("", "decade", datetime(1988, 9, 17), None) is None

    def test_a_name_with_no_date_is_left_alone(self):
        assert propose("Middle school", "unknown", None, None) is None

    def test_nothing_to_go_on_is_left_alone(self):
        assert propose("", None, None, None) is None
