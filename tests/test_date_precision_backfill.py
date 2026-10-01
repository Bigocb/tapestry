"""Guessing how precise a stored date was, for rows that predate precision.

The timeline groups by year and month, and it can only do that if a legacy row
knows whether it meant a day, a month or a year. The date itself carries the
evidence: midnight on the 1st of January is how a bare year is stored, the 1st
of any other month is a month, and any other day was a real day.
"""

from datetime import datetime

import pytest

from app.agents.capture import _precision_from_stored_date


class TestPrecisionFromStoredDate:
    def test_a_real_day_is_exact(self):
        assert _precision_from_stored_date(datetime(1976, 7, 29)) == "exact"

    def test_the_first_of_a_month_is_a_month(self):
        assert _precision_from_stored_date(datetime(1994, 6, 1)) == "month"

    def test_the_first_of_january_is_a_year(self):
        # 1 Jan is the placeholder a bare year is stored as.
        assert _precision_from_stored_date(datetime(1989, 1, 1)) == "year"

    @pytest.mark.parametrize("month", [2, 3, 6, 7, 8, 11, 12])
    def test_any_other_first_is_a_month(self, month):
        assert _precision_from_stored_date(datetime(2001, month, 1)) == "month"
