"""The telling date cursor (Issue 30).

A telling's dates anchor to the memories around them, not to the moment of
capture. "The next day" means the day after the memory before it — never
tomorrow — and a date stated once may govern several memories that follow.

Anchoring to today is deliberately never used here. ``_anchored_to_today`` in
the capture agent exists for a single memory captured in the present; a telling
is retrospective, so its only anchors are the dates it states itself.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from app.agents.capture import (
    ResolvedDate,
    _precise_date_precision,
    _resolve_fuzzy_period,
    absolute_date,
)


@dataclass(frozen=True)
class RelativeOffset:
    """A move away from the cursor, e.g. "the next day" is (day, +1).

    Units rather than a timedelta, because months and years are not fixed
    lengths of time.
    """

    unit: str  # day | week | month | year
    amount: int


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_NEXT_RE = re.compile(
    r"\bthe (?:next|following)\s+(?P<unit>day|week|month|year)\b"
)

_OFFSET_RE = re.compile(
    rf"\b(?P<amount>\d+|a couple(?: of)?|a few|several|"
    + "|".join(_NUMBER_WORDS)
    + r")\s+(?P<unit>day|week|month|year)s?\s+"
    r"(?P<direction>later|after(?:wards)?|before|earlier)\b"
)

_BACKWARDS = ("before", "earlier")


_OFFSET_PRECISION = {
    "day": "exact",
    "week": "exact",
    "month": "month",
    "year": "year",
}

# Coarser first. A shift may move down this list, never up it.
_PRECISION_RANK = {
    "unknown": 0,
    "decade": 1,
    "range": 2,
    "year": 3,
    "month": 4,
    "exact": 5,
}


def _coarser(first: str, second: str) -> str:
    """Whichever precision claims less.

    Shifting must never make a date look more certain than the anchor it came
    from: "1985" plus "two years later" is still a year, not a moment.
    """
    if _PRECISION_RANK.get(first, 0) <= _PRECISION_RANK.get(second, 0):
        return first
    return second


def _period_key(moment: datetime, precision: str):
    """A comparable key for the period a precision describes."""
    if precision == "decade":
        return moment.year // 10
    if precision == "year":
        return moment.year
    if precision == "month":
        return (moment.year, moment.month)
    if precision == "exact":
        return (moment.year, moment.month, moment.day)
    return None


def _add_months(moment: datetime, months: int) -> datetime:
    """Add whole months, clamping the day to the target month's length.

    Calendar arithmetic rather than a 365-day year: five years after
    1976-07-29 is 1981-07-29, and it is a leap year in between that would make
    a fixed day count land on the 28th.
    """
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _amount_to_int(text: str) -> Optional[int]:
    """Turn "a couple of", "several" or "two" into a number."""
    if text.isdigit():
        return int(text)
    if text.startswith("a couple"):
        return 2
    if text in ("a few", "several"):
        return 3
    return _NUMBER_WORDS.get(text)


def _absolute(text: str) -> Optional[ResolvedDate]:
    """A date the text states outright, or None.

    Fuzzy periods ("the 80s", "high school") count: they are a real answer and
    still reset the cursor, just at a coarser precision.
    """
    fuzzy = _resolve_fuzzy_period(text)
    if fuzzy is not None:
        return fuzzy

    stated = absolute_date(text)
    if stated is None:
        return None

    return ResolvedDate(
        event_date=stated,
        precision=_precise_date_precision(text),
        event_date_end=None,
        label=None,
    )


def _relative_offset(text: str) -> Optional[RelativeOffset]:
    """A move relative to the cursor, or None.

    Only phrases that move *forward* from what came before. What looks
    backwards ("last week", "three years ago") is not handled here: in a
    telling those mean something about the present, which is exactly what the
    cursor is not anchored to.
    """
    lowered = text.lower()

    match = _NEXT_RE.search(lowered)
    if match:
        return RelativeOffset(match.group("unit"), 1)

    match = _OFFSET_RE.search(lowered)
    if match:
        amount = _amount_to_int(match.group("amount"))
        if amount is not None:
            if match.group("direction") in _BACKWARDS:
                amount = -amount
            return RelativeOffset(match.group("unit"), amount)

    # "the week before", "the previous summer" — one unit back, no number.
    for unit in ("day", "week", "month", "year"):
        if re.search(rf"\bthe {unit} (?:before|earlier)\b", lowered):
            return RelativeOffset(unit, -1)
        if re.search(rf"\bthe (?:previous|preceding|prior) {unit}\b", lowered):
            return RelativeOffset(unit, -1)

    return None


def _shift(date: ResolvedDate, offset: RelativeOffset) -> ResolvedDate:
    """Move a resolved date by an offset, coarsening its precision."""
    base = date.event_date
    if base is None:
        return date

    if offset.unit == "day":
        shifted = base + timedelta(days=offset.amount)
    elif offset.unit == "week":
        shifted = base + timedelta(weeks=offset.amount)
    elif offset.unit == "month":
        shifted = _add_months(base, offset.amount)
    else:
        shifted = _add_months(base, offset.amount * 12)

    label = date.label
    if label is not None and _period_key(shifted, date.precision) != _period_key(
        base, date.precision
    ):
        # The wording described the anchor. Once the date leaves that period the
        # words are no longer true of it — "August 2003" cannot label 2005.
        label = None

    return ResolvedDate(
        event_date=shifted,
        precision=_coarser(date.precision, _OFFSET_PRECISION[offset.unit]),
        event_date_end=None,
        label=label,
    )


def resolve_telling_dates(
    texts: Sequence[str],
    known: Optional[Sequence[Optional[ResolvedDate]]] = None,
) -> list[ResolvedDate]:
    """Resolve one date per segment, threading a cursor through them in order.

    A stated date resets the cursor; a relative phrase is measured from it. A
    phrase with nothing to anchor to stays undated rather than guessed at.

    ``known[i]`` is a date already resolved for segment i — typically the one a
    segmenter supplied after reading the whole account. It wins and anchors the
    cursor, so a memory whose date is implied rather than stated in its own text
    is not thrown away.
    """
    cursor: Optional[ResolvedDate] = None
    resolved: list[ResolvedDate] = []

    for index, text in enumerate(texts):
        known_here: Optional[ResolvedDate] = None
        if known is not None and index < len(known):
            known_here = known[index]

        # A relative phrase belongs to the cursor, not the segmenter. Only the
        # cursor knows what came before: shown "The next day" on its own, a
        # segmenter answers with the nearest month it can see, which is the
        # month before rather than the day after.
        offset = _relative_offset(text)
        if offset is not None and cursor is not None:
            cursor = _shift(cursor, offset)
            resolved.append(cursor)
            continue

        # Otherwise the segmenter's own date wins: it read the whole account.
        if known_here is not None and known_here.event_date is not None:
            cursor = known_here
            resolved.append(known_here)
            continue

        # It looked and answered "no date". That is not "nothing here", but it
        # does mean the text's *stated* dates are left alone — re-deriving them
        # puts back the incidental years its guard just removed.
        settled_as_undated = known_here is not None

        if not settled_as_undated:
            stated = _absolute(text)
            if stated is not None:
                cursor = stated
                resolved.append(stated)
                continue

        resolved.append(known_here if known_here is not None else ResolvedDate())

    return resolved
