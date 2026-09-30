"""Telling Agent: split one recounting into the memories it contains.

A telling is an account that holds several memories at once. This module
proposes where one memory ends and the next begins. The user reviews that
split before anything is saved, so the job here is to produce a good first
draft — never to be authoritative.

Segments carry verbatim transcript text rather than character offsets. Models
miscount offsets, and the transcript on the telling row stays the source of
truth, so exact partitioning is not needed.
"""

from dataclasses import dataclass

from app.agents.capture import (
    _build_structured_memory,
    _call_ollama_chat,
    structure_memory,
)
from app.models.schemas import StructuredMemory


SEGMENTATION_SYSTEM_PROMPT = """You are the Telling Agent for MEMIND, a memory-capture system.
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

Rules:
- The account may be transcribed speech. It can have no paragraphs and unreliable punctuation. Split on changes of subject, time or place, never on sentence boundaries.
- Relative time ("the next day", "two years later") belongs to the memory whose text contains it.
- Never invent a memory that is not in the account. If the whole account is one memory, return one segment covering all of it.
- Every word of the account should appear in exactly one segment's text.

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


def _build_segmentation_prompt(transcript: str) -> str:
    return (
        "Split this account into the memories it contains:\n\n"
        f"{transcript}\n\nSegments JSON:"
    )


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
        segments.append(
            ProposedSegment(
                text=text,
                structured=_build_structured_memory(item, text),
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


async def segment_transcript(transcript: str) -> list[ProposedSegment]:
    """Split a recounting into the memories it contains.

    Falls back to a single segment covering the whole account whenever the
    model is unreachable or returns nothing usable.
    """
    if transcript and transcript.strip():
        try:
            raw = await _call_ollama_chat(
                _build_segmentation_prompt(transcript), SEGMENTATION_SYSTEM_PROMPT
            )
            segments = _parse_segments(raw)
            if segments:
                return segments
        except Exception:
            pass

    return [await _fallback_segment(transcript)]
