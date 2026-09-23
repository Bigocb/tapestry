"""Datetime helpers.

SQLite does not store timezone information, so ORM-written timestamps come
back naive, while values written through raw SQL (e.g. the startup backfill)
can carry an offset. Comparing the two raises
``TypeError: can't compare offset-naive and offset-aware datetimes``.
Normalise every stored datetime before comparing or ordering.
"""

from datetime import datetime, timezone
from typing import Optional


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return a UTC-aware datetime, treating naive values as already UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
