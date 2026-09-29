"""Write-path rules shared by every way a Memory row gets created.

Live capture, committing a telling, and manual edits all have to apply the same
two rules: resolved (possibly fuzzy) date fields travel together, and a memory
with no time signal at all belongs in the review queue. Keeping them here stops
route modules from reaching into each other.
"""

from app.db.models import Memory


def apply_memory_date_fields(memory: Memory, source) -> None:
    """Copy resolved date fields onto the row.

    ``source`` is anything carrying the same four fields — a ``StructuredMemory``
    from the Capture Agent, or a telling segment awaiting review. Keeping them
    together is what stops a fuzzy period (``decade``/``range`` plus a label)
    from being flattened into a single day.
    """
    memory.event_date = source.event_date
    memory.date_precision = getattr(source, "date_precision", None)
    memory.event_date_end = getattr(source, "event_date_end", None)
    memory.date_label = getattr(source, "date_label", None)


def apply_review_flags(memory: Memory) -> None:
    """Flag a memory for the review queue when the pipeline couldn't complete.

    A missing event date is the current reason: without one the memory cannot be
    placed on the timeline. A fuzzy period (decade, range, named life period) is
    a real answer, not a missing one, so a dated-but-fuzzy memory is NOT sent to
    review.
    """
    has_time_signal = (
        memory.event_date is not None
        or memory.date_precision in ("decade", "range")
        or bool(memory.date_label)
    )
    if has_time_signal:
        memory.needs_review = False
        memory.review_reason = None
    else:
        memory.needs_review = True
        memory.review_reason = "missing_date"
