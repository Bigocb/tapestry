"""Capture Agent: turn raw memory input into structured StructuredMemory."""

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.models.schemas import EntityData, StructuredMemory

# Common words that look capitalized but aren't names/places.
_DENYLIST = {
    "i", "we", "you", "he", "she", "it", "they", "me", "us", "them", "my",
    "your", "his", "her", "its", "our", "their", "this", "that", "these",
    "those", "the", "a", "an", "and", "or", "but", "if", "then", "than",
    "as", "at", "by", "for", "from", "in", "into", "of", "on", "to", "with",
    "about", "after", "before", "during", "over", "under", "again", "once",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday",
}

_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma",
    "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}

_PLACE_PREPS = {"in", "at", "from", "near", "around"}
_PERSON_PREPS = {"to", "with", "by", "and"}

DEFAULT_OLLAMA_API_BASE = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL = "gemma4:31b"
REQUEST_TIMEOUT_SECONDS = 30.0


CAPTURE_SYSTEM_PROMPT = """You are the Capture Agent for MEMIND, a memory-capture system.
Your job is to take a user's raw memory input and return a concise structured JSON object.
Do NOT resolve ambiguities (e.g., leave "that meeting" as-is). Do NOT add information you cannot infer from the input.

Output a single JSON object with exactly these fields:
- title: string, 3-12 words
- summary: string, 1-3 sentences
- entities: list of objects with keys type, value, and optional metadata. Extract all named people as "person" entities (full names), all locations as "place" entities, and any dates as "date" entities.
- mood: string or null (a single word describing the feeling, e.g. happy, anxious, excited)
- importance_level: integer 1-10
- initial_tags: list of lowercase string tags, 1-5 items
- event_date: ISO 8601 datetime string (e.g. "1976-07-29T00:00:00") or null. Infer the best date from the text, including historical dates like "July 29, 1976".

Allowed entity types: person, place, date, event, concept.

Example input:
"On July 29, 1976 I was born in Conway, South Carolina to Robert Jules Cloutier and Virginia Smith Cloutier."

Example output:
{
  "title": "Birth in Conway, South Carolina",
  "summary": "I was born on July 29, 1976 in Conway, South Carolina to Robert Jules Cloutier and Virginia Smith Cloutier.",
  "entities": [
    {"type": "person", "value": "Robert Jules Cloutier"},
    {"type": "person", "value": "Virginia Smith Cloutier"},
    {"type": "place", "value": "Conway, South Carolina"},
    {"type": "date", "value": "July 29, 1976"}
  ],
  "mood": null,
  "importance_level": 8,
  "initial_tags": ["birth", "conway", "south carolina", "1976", "family"],
  "event_date": "1976-07-29T00:00:00"
}

Return ONLY valid JSON. Do not wrap it in markdown fences or add explanation."""


def _build_capture_prompt(raw_input: str) -> str:
    return f"Structure the following memory into JSON:\n\n{raw_input}\n\nStructured JSON:"


def _ollama_config() -> tuple[str, str, Optional[str]]:
    """Return (api_base, model, api_key)."""
    api_base = os.environ.get("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENWIKI_API_KEY")
    return api_base, model, api_key


async def _call_ollama_chat(prompt: str) -> dict:
    """Call the Ollama Chat API and return the raw message content as a dict.

    Raises RuntimeError on network or parsing failures so the caller can fall back.
    """
    api_base, model, api_key = _ollama_config()
    # Support both https://ollama.com/v1 and http://localhost:11434 style bases.
    if api_base.endswith("/v1"):
        url = f"{api_base}/chat/completions"
    else:
        url = f"{api_base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": CAPTURE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    # Some models wrap JSON in markdown fences; strip them.
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
    if content.endswith("```"):
        content = content.rsplit("\n", 1)[0]
    content = content.strip()
    return json.loads(content)


def _is_sentence_start(text: str, start: int) -> bool:
    """Return True if the match at `start` begins a sentence."""
    preceding = text[:start].strip()
    if not preceding:
        return True
    return preceding[-1] in {".", "!", "?", "\n"}


def _extract_city_state_places(text: str) -> list[EntityData]:
    """Find US city + state patterns, e.g. 'Conway, South Carolina'."""
    entities: list[EntityData] = []
    seen: set[str] = set()
    tokens = [
        (m.group(), m.start(), m.end())
        for m in re.finditer(r"\b\w+\b", text)
    ]
    lowered_text = text.lower()

    for i, (word, start, end) in enumerate(tokens):
        # Try single-word and two-word state names.
        state: str | None = None
        state_end = end
        if i + 1 < len(tokens):
            two_word = f"{word.lower()} {tokens[i + 1][0].lower()}"
            if two_word in _US_STATES:
                state = two_word.title()
                state_end = tokens[i + 1][2]
        if state is None and word.lower() in _US_STATES:
            state = word.lower().title()

        if state is None:
            continue

        # Walk backwards to collect up to 3 city words (stop at common words/prepositions).
        city_words: list[str] = []
        j = i - 1
        non_name_words = {"and", "or", "but", "the", "in", "on", "at", "to", "from", "with", "by", "for", "of"}
        while j >= 0 and len(city_words) < 3:
            prev_word, prev_start, prev_end = tokens[j]
            lowered_prev = prev_word.lower()
            if lowered_prev not in _DENYLIST and lowered_prev not in non_name_words:
                city_words.insert(0, prev_word)
                j -= 1
            else:
                break

        if not city_words:
            continue

        city = " ".join(w.title() for w in city_words)
        place = f"{city}, {state}"
        key = place.lower()
        if key not in seen:
            seen.add(key)
            entities.append(EntityData(type="place", value=place, metadata=None))

    return entities


def _extract_entities_fallback(raw_input: str) -> list[EntityData]:
    """Deterministic fallback for people and places when the LLM returns nothing.

    Looks for capitalized word sequences (2-4 words) and classifies them based
    on nearby prepositions and known place names.
    """
    entities: list[EntityData] = []
    seen: set[str] = set()
    text = raw_input
    lowered = text.lower()

    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    # 1) Known city + state pattern.
    for place_entity in _extract_city_state_places(text):
        key = _norm(place_entity.value)
        if key not in seen:
            seen.add(key)
            entities.append(place_entity)

    # 2) Capitalized sequences of 2-4 words.
    non_name_words = {"and", "or", "but", "the", "in", "on", "at", "to", "from", "with", "by", "for", "of"}
    for match in re.finditer(r"\b([A-Z][a-zA-Z\.]*(?:\s+[A-Z][a-zA-Z\.]*){1,3})\b", text):
        value = match.group(1)
        key = value.lower()
        norm_key = _norm(value)
        words = key.split()

        if norm_key in seen or key in _DENYLIST or _is_sentence_start(text, match.start()):
            continue
        # Reject candidates containing conjunctions/prepositions in the middle.
        if any(w in non_name_words for w in words):
            continue
        # Skip standalone state names (handled above).
        if key in _US_STATES:
            continue

        # Classify by preceding context.
        window_start = max(0, match.start() - 40)
        window = lowered[window_start:match.start()]
        tokens = re.findall(r"\b\w+\b", window)
        nearby = set(tokens[-3:])

        place_like = any(p in nearby for p in _PLACE_PREPS)
        ends_with_state = any(key.endswith(f" {state}") for state in _US_STATES)

        if place_like and ends_with_state:
            entities.append(EntityData(type="place", value=value, metadata=None))
        else:
            entities.append(EntityData(type="person", value=value, metadata=None))

        seen.add(norm_key)

    return entities


def _extract_tags_fallback(raw_input: str, entities: list[EntityData]) -> list[str]:
    """Build simple keyword tags when the LLM doesn't provide any."""
    stop_words = _DENYLIST | {"was", "were", "been", "have", "has", "had", "do", "does", "did", "am", "are", "is", "be"}
    entity_values = {e.value.lower() for e in entities}
    words = re.findall(r"\b([a-z]{3,})\b", raw_input.lower())
    counts = Counter(w for w in words if w not in stop_words and w not in entity_values)
    # Prefer longer, more specific words
    candidates = sorted(counts.keys(), key=lambda w: (-counts[w], -len(w)))
    return [w.lower()[:50] for w in candidates[:5]]


def _extract_event_date(raw_input: str) -> Optional[datetime]:
    """Try to infer an event date from common temporal phrases in raw text."""
    text = raw_input.lower()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Explicit ISO / American style dates
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_input)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Relative phrases
    if "yesterday" in text:
        return today - timedelta(days=1)
    if "today" in text:
        return today
    if "last week" in text or "a week ago" in text:
        return today - timedelta(days=7)
    if "last month" in text or "a month ago" in text:
        return today - timedelta(days=30)
    if "a year ago" in text or "last year" in text:
        return today - timedelta(days=365)

    match = re.search(r"(\d+)\s+days?\s+ago", text)
    if match:
        return today - timedelta(days=int(match.group(1)))
    match = re.search(r"(\d+)\s+weeks?\s+ago", text)
    if match:
        return today - timedelta(weeks=int(match.group(1)))
    match = re.search(r"(\d+)\s+months?\s+ago", text)
    if match:
        return today - timedelta(days=int(match.group(1)) * 30)
    match = re.search(r"(\d+)\s+years?\s+ago", text)
    if match:
        return today - timedelta(days=int(match.group(1)) * 365)

    # Seasons: "last summer", "this winter", "in the spring", "two summers ago".
    season_months = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}
    season_word = next(
        (s for s in season_months if re.search(rf"\b{s}s?\b", text)), None
    )
    if season_word:
        year = today.year
        if re.search(r"\b(one|a|last)\s+year\b", text):
            year = today.year - 1
        elif "two" in text and season_word in text:
            year = today.year - 2
        elif re.search(r"\bthis\b", text):
            year = today.year
        return datetime(year, season_months[season_word], 1).replace(tzinfo=timezone.utc)

    # Weekdays: "on Friday", "last Tuesday", "this Monday" (most recent past).
    weekday_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    weekday_word = next(
        (name for name in weekday_names if re.search(rf"\b{name}\b", text)), None
    )
    if weekday_word and re.search(r"\b(last|this|on|past)\b", text):
        target = weekday_names[weekday_word]
        days_since = (today.weekday() - target) % 7
        if days_since == 0 and "last" in text:
            days_since = 7
        return today - timedelta(days=days_since)

    # Holidays with an optional year: "Christmas 2021", "Christmas".
    holiday_months = {
        "christmas": (12, 25), "new year": (1, 1), "new year's": (1, 1),
        "halloween": (10, 31), "valentine": (2, 14),
        "thanksgiving": (11, 28), "independence day": (7, 4),
    }
    for name, (month, day) in holiday_months.items():
        holiday_match = re.search(rf"{name}(?:'s)?(?:\s+(\d{{4}}))?", text)
        if holiday_match:
            year = int(holiday_match.group(1)) if holiday_match.group(1) else today.year
            return datetime(year, month, day).replace(tzinfo=timezone.utc)

    # Full month-day-year, e.g. "July 29, 1976" or "July 29th, 1976"
    month_day_year_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        text,
    )
    if month_day_year_match:
        try:
            month = month_day_year_match.group(1)
            day = month_day_year_match.group(2)
            year = month_day_year_match.group(3)
            dt = datetime.strptime(f"{month} {day} {year}", "%B %d %Y")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Numeric dates: 07/29/1976 or 1976-07-29
    numeric_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_input)
    if numeric_match:
        try:
            return datetime.strptime(numeric_match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Month year, e.g. "July 2025"
    month_year_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b",
        text,
    )
    if month_year_match:
        try:
            dt = datetime.strptime(f"{month_year_match.group(1)} {month_year_match.group(2)}", "%B %Y")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Bare four-digit year, e.g. "Back in 2019 I started...".
    year_match = re.search(r"\b(19|20)\d{2}\b", raw_input)
    if year_match:
        try:
            return datetime(int(year_match.group(0)), 1, 1).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def _fallback_structured_memory(raw_input: str) -> StructuredMemory:
    """Produce a safe fallback when the LLM fails."""
    entities = _extract_entities_fallback(raw_input)
    return StructuredMemory(
        title=raw_input[:100] if len(raw_input) <= 100 else raw_input[:97] + "...",
        summary=raw_input,
        entities=entities,
        mood=None,
        importance_level=5,
        initial_tags=_extract_tags_fallback(raw_input, entities),
        event_date=_extract_event_date(raw_input),
    )


def _normalize_entities(raw_entities: list[dict]) -> list[EntityData]:
    """Convert raw entity dicts to EntityData, skipping invalid entries."""
    normalized = []
    allowed_types = {"person", "place", "date", "event", "concept"}
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        entity_type = item.get("type")
        value = item.get("value")
        if entity_type not in allowed_types or not value:
            continue
        metadata = item.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            metadata = None
        normalized.append(
            EntityData(type=entity_type, value=str(value), metadata=metadata)
        )
    return normalized


def _build_structured_memory(raw_dict: dict, raw_input: str) -> StructuredMemory:
    """Build a StructuredMemory from the parsed LLM response dict.

    Sanitizes fields so the result always validates even if the model is sloppy.
    """
    title = str(raw_dict.get("title") or "")[:255]
    if not title:
        title = raw_input[:100] if len(raw_input) <= 100 else raw_input[:97] + "..."

    summary = str(raw_dict.get("summary") or "")
    if not summary:
        summary = raw_input

    mood = raw_dict.get("mood")
    if mood is not None:
        mood = str(mood)[:50] or None

    importance_level = raw_dict.get("importance_level")
    try:
        importance_level = int(importance_level)
    except (TypeError, ValueError):
        importance_level = 5
    importance_level = max(1, min(10, importance_level))

    raw_entities = raw_dict.get("entities") or []
    if not isinstance(raw_entities, list):
        raw_entities = []
    entities = _normalize_entities(raw_entities)

    raw_tags = raw_dict.get("initial_tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    initial_tags = [str(tag).lower()[:50] for tag in raw_tags if tag]

    # If the LLM left entities/tags empty, use deterministic fallback extraction.
    if not entities:
        entities = _extract_entities_fallback(raw_input)
    if not initial_tags:
        initial_tags = _extract_tags_fallback(raw_input, entities)

    event_date = raw_dict.get("event_date")
    if isinstance(event_date, str):
        try:
            event_date = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
        except ValueError:
            event_date = _extract_event_date(raw_input)
    elif not isinstance(event_date, datetime):
        event_date = _extract_event_date(raw_input)

    return StructuredMemory(
        title=title,
        summary=summary,
        entities=entities,
        mood=mood,
        importance_level=importance_level,
        initial_tags=initial_tags,
        event_date=event_date,
    )


async def structure_memory(raw_input: str) -> StructuredMemory:
    """Convert raw memory text into a structured memory using the Capture Agent.

    If the Ollama API is unreachable, times out, or returns invalid JSON, a safe
    fallback StructuredMemory is returned instead of raising an error.
    """
    if not raw_input or not raw_input.strip():
        return _fallback_structured_memory(raw_input)

    try:
        raw_dict = await _call_ollama_chat(_build_capture_prompt(raw_input))
        return _build_structured_memory(raw_dict, raw_input)
    except Exception:
        return _fallback_structured_memory(raw_input)
