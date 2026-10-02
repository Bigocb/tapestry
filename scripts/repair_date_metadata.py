"""One-off: make a memory's stored date fields agree with what it says.

The timeline reads a memory's wording before its precision, so the display is
already right. This repairs the rows underneath, where the model's stored
precision and the stored placeholder date contradict the memory.

Evidence, strongest first:

  1. The label, when it states a period: "1988" is a year, "September 2000" a
     month, "2/18/1999" a day, "1987-1990" a range, "the 80s" a decade.
Nothing is read out of the raw text. Prose mentions a period for reasons other
than dating the memory — "Ryan's 70s Dodge Dart" and "the DJ played 2000s
throwbacks" are about the car and the music, not the day — so a re-read there
would move rows to the wrong decade. Rows with no usable label are left for the
user to date by hand.

It never sharpens beyond what the label states, it never destroys a real day the
label agrees with, and it never widens a decade the row already narrowed
("early 1980s" is 1980-1983, not 1980-1989).

Dry run by default. Pass --apply to write.
"""

import argparse
import asyncio
import re
from datetime import datetime

from sqlalchemy import text

from app.db import AsyncSessionLocal

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
MONTHS = {name: index for index, name in enumerate(MONTH_NAMES, 1)}

# The `s` is required, so a bare "1980" is a year and "1980s" is a decade.
_DECADE = re.compile(r"\b((?:1[89]|20)?\d0)'?s\b")


def label_period(label: str):
    """The period a label states, or None when it only names something."""
    value = (label or "").strip()
    if not value:
        return None

    match = re.fullmatch(
        r"((?:18|19|20)\d{2})\s*[-–—]\s*((?:18|19|20)\d{2})", value
    )
    if match:
        return ("range", datetime(int(match[1]), 1, 1), datetime(int(match[2]), 12, 31))

    match = re.fullmatch(
        r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:18|19|20)\d{2})", value
    )
    if match and match[1].lower() in MONTHS:
        return (
            "exact",
            datetime(int(match[3]), MONTHS[match[1].lower()], int(match[2])),
            None,
        )

    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if match:
        return ("exact", datetime(int(match[3]), int(match[1]), int(match[2])), None)

    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return ("exact", datetime(int(match[1]), int(match[2]), int(match[3])), None)

    match = re.fullmatch(r"([A-Za-z]+)\s+((?:18|19|20)\d{2})", value)
    if match and match[1].lower() in MONTHS:
        return ("month", datetime(int(match[2]), MONTHS[match[1].lower()], 1), None)

    match = _DECADE.search(value.lower())
    if match:
        digits = match[1]
        year = (
            int(digits)
            if len(digits) == 4
            else (2000 if int(digits) < 30 else 1900) + int(digits)
        )
        start = (year // 10) * 10
        return ("decade", datetime(start, 1, 1), datetime(start + 9, 12, 31))

    match = re.fullmatch(r"((?:18|19|20)\d{2})", value)
    if match:
        return ("year", datetime(int(match[1]), 1, 1), None)

    return None


def propose(label, precision, event_date, event_end):
    """What this row's (precision, start, end, label) should be, or None."""
    period = label_period(label)
    if period is None:
        # No usable label. A placeholder precision sitting on a real day is the
        # precision that is wrong: the day is the more specific truth. This is
        # the shape a date lands in when an exact date was set but the old
        # editor left a stale "decade" beside it. Nothing is read from the raw
        # text — only the date the row already stores.
        if (
            precision in ("month", "year", "decade", "range")
            and event_date is not None
            and event_date.day != 1
        ):
            return ("exact", event_date, event_end, None)
        return None

    kind, start, end = period
    # A decade the row already records is left as it is: the stored end carries
    # the narrowing in "early 1980s" (1983), which a plain decade end (1989)
    # would widen away.
    if kind == "decade" and precision == "decade" and event_date is not None:
        return ("decade", event_date, event_end, None)
    # A month-only label must not throw away a real day that agrees with it.
    if (
        kind == "month"
        and precision == "exact"
        and event_date is not None
        and event_date.day != 1
        and (event_date.year, event_date.month) == (start.year, start.month)
    ):
        return ("exact", event_date, event_end, None)
    return (kind, start, end, None)


def fmt(moment):
    return moment.date().isoformat() if moment else "-"


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, raw_input, structured_content, event_date, "
                    "event_date_end, date_precision, date_label FROM memories"
                )
            )
        ).fetchall()

        changes = []
        for row in rows:
            (
                memory_id,
                raw_input,
                content,
                event_date,
                event_end,
                precision,
                label,
            ) = row
            precision = precision or None
            label = (label or "").strip()

            proposed = propose(label, precision, event_date, event_end)
            if proposed is None:
                continue
            new_precision, new_start, new_end, new_label = proposed
            if (new_precision, new_start, new_end) == (
                precision,
                event_date,
                event_end,
            ):
                continue

            title = content.get("title") if isinstance(content, dict) else None
            changes.append(
                (
                    str(memory_id),
                    title or (raw_input or "")[:40],
                    label,
                    precision,
                    event_date,
                    new_precision,
                    new_start,
                    new_end,
                    new_label,
                )
            )

        print(f"{len(changes)} rows would change\n")
        print(f"{'memory':<36}{'precision':<20}{'date':<24}->  {'precision':<10}date")
        print("-" * 108)
        for change in changes:
            (
                _id,
                title,
                label,
                precision,
                event_date,
                new_precision,
                new_start,
                _new_end,
                _new_label,
            ) = change
            print(
                f"{title[:34]:<36}[{(label or '-')[:14]:<14}] "
                f"{(precision or '-'):<9}{fmt(event_date):<12}->  "
                f"{new_precision:<9}{fmt(new_start)}"
            )

        if not apply:
            print("\nDry run. Re-run with --apply to write.")
            return

        for change in changes:
            (
                memory_id,
                _title,
                _label,
                _precision,
                _event_date,
                new_precision,
                new_start,
                new_end,
                new_label,
            ) = change
            await session.execute(
                text(
                    "UPDATE memories SET date_precision = :p, event_date = :s, "
                    "event_date_end = :e, "
                    "date_label = COALESCE(:l, date_label) WHERE id = :i"
                ),
                {
                    "p": new_precision,
                    "s": new_start,
                    "e": new_end,
                    "l": new_label,
                    "i": memory_id,
                },
            )
        await session.commit()
        print(f"\nApplied {len(changes)} changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
