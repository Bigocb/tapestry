"""Telling Agent: split one recounting into the memories it contains.

A telling is an account that holds several memories at once. This module
proposes where one memory ends and the next begins. The user reviews that
split before anything is saved, so the job here is to produce a good first
draft — never to be authoritative.

Segments carry verbatim transcript text rather than character offsets. Models
miscount offsets, and the transcript on the telling row stays the source of
truth, so exact partitioning is not needed.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.agents.capture import (
    ResolvedDate,
    _build_structured_memory,
    _call_ollama_chat,
    structure_memory,
)
from app.agents.telling_dates import (
    TellingFrame,
    derive_frame,
    inherit_frame,
    resolve_telling_dates,
)
from app.models.schemas import StructuredMemory


SEGMENTATION_SYSTEM_PROMPT = """You are the Telling Agent for Tapestry, a memory-capture system.
A user has recounted several memories in one go. Split that account into the individual memories it contains.

Output a single JSON object with one field:
- segments: an ordered list of objects, each with:
  - text: the exact words from the account that belong to this memory, copied verbatim. Do not paraphrase, correct or shorten them, and do not return character offsets.
  - title: string, 3-12 words
  - summary: string, 1-3 sentences
  - entities: list of objects with keys type, value and optional metadata. Extract all named people as "person" entities (full names), all locations as "place", and any dates as "date".
    - For a place contained in a larger place, set metadata.parent to the larger place's name.
    - For a person, metadata may include "relation" (e.g. "wife") when the text states it. Do not invent relationships.
  - mood: string or null (a single word, e.g. happy, anxious, excited)
  - importance_level: integer 1-10
  - initial_tags: list of lowercase string tags, 1-5 items
  - event_date: ISO 8601 datetime string (e.g. "1985-07-01T00:00:00") or null
  - date_precision: one of exact, month, year, decade, range, unknown
  - date_label: string or null. The account's own wording for a fuzzy period, e.g. "High school", "early 2000s".

Rules:
- The account may be transcribed speech. It can have no paragraphs and unreliable punctuation. Split on changes of subject, time or place, never on sentence boundaries.
- Relative time ("the next day", "two years later") belongs to the memory whose text contains it.
- Never invent a memory that is not in the account. If the whole account is one memory, return one segment covering all of it.
- Every word of the account should appear in exactly one segment's text.

Dating rules — these matter more than they look:
- event_date is when the memory happened. Never take it from a date that merely appears in the text: when the music was from, a birthday mentioned in passing, a year written on a sign. If the account does not say when the memory happened, set event_date to null and date_precision to "unknown".
- Never invent a year. If the account gives a day and month but no year ("August 15th"), set event_date to null — do not supply a placeholder year such as 1900.
- Always include event_date, date_precision and date_label, using null when you have nothing to say.
- If the account states a period that frames several memories ("high school", "the summer of 1985"), give every memory that period covers the same wording as its date_label, so the memories from one account agree about when they took place.

Allowed entity types: person, place, date, event, concept.

Example account:
"I was born in Conway in 1976. We moved to Raleigh when I was five."

Example output:
{
  "segments": [
    {"text": "I was born in Conway in 1976.", "title": "Born in Conway", "summary": "Born in Conway in 1976.", "entities": [{"type": "place", "value": "Conway"}], "mood": null, "importance_level": 9, "initial_tags": ["birth", "conway"], "event_date": "1976-01-01T00:00:00"},
    {"text": "We moved to Raleigh when I was five.", "title": "Moving to Raleigh", "summary": "The family moved to Raleigh at age five.", "entities": [{"type": "place", "value": "Raleigh"}], "mood": null, "importance_level": 7, "initial_tags": ["moving", "raleigh"], "event_date": "1981-01-01T00:00:00"}
  ]
}

Return ONLY valid JSON. Do not wrap it in markdown fences or add explanation."""


@dataclass
class ProposedSegment:
    """One proposed memory, cut from a transcript and not yet reviewed."""

    text: str
    structured: StructuredMemory
    # True when the segmenter itself answered about this memory's date, even if
    # the answer was "none". The date cursor must not second-guess that from the
    # text — doing so puts back the false dates _respect_explicit_null_dates and
    # _drop_unsupported_exact_date just removed.
    date_settled: bool = False


@dataclass
class SegmentationResult:
    """A telling's proposed split, and the period the account is about.

    The frame belongs to the telling rather than to any one memory, so it
    travels with the result instead of being repeated on every segment.
    """

    segments: list["ProposedSegment"] = field(default_factory=list)
    frame_label: Optional[str] = None
    frame_date: Optional[datetime] = None


def _build_segmentation_prompt(transcript: str) -> str:
    return (
        "Split this account into the memories it contains:\n\n"
        f"{transcript}\n\nSegments JSON:"
    )


def _respect_explicit_null_dates(
    structured: StructuredMemory, item: dict
) -> None:
    """Let the segmenter's explicit "no date" beat the deterministic scan.

    ``_build_structured_memory`` re-derives a date from any year-like phrase, which
    is right for a single capture but wrong for a segment: "the DJ played early
    2000s throwbacks" says when the music was from, not when the memory happened.
    The segmenter reads the whole account, so when it answers explicitly — even
    with null — that answer is authoritative. An omitted key still falls back.
    """
    if item.get("event_date", "absent") is not None:
        return

    structured.event_date = None
    structured.event_date_end = None
    if item.get("date_precision") is None:
        structured.date_precision = "unknown"
    if item.get("date_label") is None:
        structured.date_label = None


def _segment_date(segment: ProposedSegment) -> Optional[ResolvedDate]:
    """What this segment already says about its date, if anything.

    Returns None when the segment is genuinely open to inference by the story
    cursor, and an empty ResolvedDate when the segmenter answered "no date" —
    a distinction the cursor needs, since only the first should be re-derived
    from the text.
    """
    structured = segment.structured
    has_signal = (
        structured.event_date is not None
        or bool(structured.date_label)
        or structured.date_precision not in (None, "unknown")
    )

    if not has_signal:
        return ResolvedDate() if segment.date_settled else None

    return ResolvedDate(
        event_date=structured.event_date,
        precision=structured.date_precision or "unknown",
        event_date_end=structured.event_date_end,
        label=structured.date_label,
    )


def _apply_story_dates(segments: list[ProposedSegment]) -> TellingFrame:
    """Date the segments from the narrative, and return the telling's period.

    Runs after parsing, because it needs every segment's text at once. A
    segment that already carries a date keeps it and anchors the cursor for
    those that follow; anything the cursor cannot reach inherits the telling's
    own period rather than going undated.
    """
    known = [_segment_date(segment) for segment in segments]
    resolved = resolve_telling_dates(
        [segment.text for segment in segments], known
    )

    # Cursor first, frame second: a precise answer always beats a vague one, so
    # only what is still undated inherits the telling's own wording.
    frame = derive_frame(resolved)
    resolved = inherit_frame(resolved, frame)

    for segment, date in zip(segments, resolved):
        # Nothing to say: leave whatever the segment already had rather than
        # clearing a label the model derived.
        if date.event_date is None and not date.label:
            continue

        structured = segment.structured
        structured.event_date = date.event_date
        structured.date_precision = date.precision
        structured.event_date_end = date.event_date_end
        structured.date_label = date.label

    return frame


def _year_is_supported(text: str, year: int) -> bool:
    """Was this year plausibly read out of the text?

    Accepts the four-digit year, or its last two digits, so "fall of 95" still
    supports 1995.
    """
    if str(year) in text:
        return True
    return re.search(rf"\b{year % 100:02d}\b", text) is not None


def _drop_unsupported_exact_date(structured: StructuredMemory, text: str) -> None:
    """Reject an *exact* date whose year never appears in the segment.

    "August 15th" states no year; a model that answers 1900-08-15 has invented
    one, and an invented year is worse than no date because it silently files
    the memory in the wrong century.

    Only exact dates are policed. A decade or range is an honestly fuzzy answer
    — "the 80s" legitimately resolves to a representative year that need not be
    written out — so those are left alone.
    """
    if structured.event_date is None or structured.date_precision != "exact":
        return
    if _year_is_supported(text, structured.event_date.year):
        return

    structured.event_date = None
    structured.event_date_end = None
    structured.date_precision = "unknown"


def _parse_segments(raw: object) -> list[ProposedSegment]:
    """Validate the model's segments, dropping anything unusable.

    Every segment is normalised through the same validation single capture
    uses, so a proposed memory is shaped exactly like a captured one.
    """
    if not isinstance(raw, dict):
        return []

    items = raw.get("segments")
    if not isinstance(items, list):
        return []

    segments: list[ProposedSegment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        text = text.strip()
        structured = _build_structured_memory(item, text)
        _respect_explicit_null_dates(structured, item)
        _drop_unsupported_exact_date(structured, text)
        segments.append(
            ProposedSegment(
                text=text,
                structured=structured,
                date_settled="event_date" in item,
            )
        )
    return segments


async def _fallback_segment(transcript: str) -> ProposedSegment:
    """One segment covering the whole account.

    Identical to the behaviour before segmentation existed, so a model outage
    degrades to a reviewable single memory rather than losing the words.
    """
    return ProposedSegment(
        text=transcript, structured=await structure_memory(transcript)
    )


async def segment_transcript(transcript: str) -> SegmentationResult:
    """Split a recounting into the memories it contains, and frame the telling.

    Falls back to a single segment covering the whole account whenever the model
    is unreachable or returns nothing usable. The fallback is dated the same way
    everything else is, so an outage costs the split but not the dates.
    """
    segments: list[ProposedSegment] = []

    if transcript and transcript.strip():
        try:
            raw = await _call_ollama_chat(
                _build_segmentation_prompt(transcript), SEGMENTATION_SYSTEM_PROMPT
            )
            segments = _parse_segments(raw)
        except Exception:
            segments = []

    if not segments:
        segments = [await _fallback_segment(transcript)]

    frame = _apply_story_dates(segments)
    return SegmentationResult(
        segments=segments,
        frame_label=frame.label,
        frame_date=frame.date,
    )
