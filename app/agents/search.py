"""Search Agent: parse natural language queries into structured SearchQuery."""

import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.models.schemas import SearchFilters, SearchQuery

DEFAULT_OLLAMA_API_BASE = "https://api.ollama.com"
DEFAULT_OLLAMA_MODEL = "glm-5.1"
REQUEST_TIMEOUT_SECONDS = 8.0


SEARCH_SYSTEM_PROMPT = """You are the Search Agent for MEMIND.
Your job is to parse a user's natural language query into a structured search request.

Output a single JSON object with exactly these fields:
- text: string of relevant keywords for full-text search (or null if none)
- semantic: string describing the semantic intent (or null if none)
- filters: object with optional fields:
    - date_range_start: ISO 8601 datetime string or null
    - date_range_end: ISO 8601 datetime string or null
    - tags: list of tag strings or null
    - mood: string or null
    - importance_min: integer 1-10 or null
    - importance_max: integer 1-10 or null
- limit: integer 1-100 (default 20)
- offset: integer >= 0 (default 0)

Guidelines:
- Extract concrete keywords for `text` (people, places, events).
- Put broader conceptual intent in `semantic`.
- Infer date ranges from expressions like "Q1", "last month", "this week", "yesterday", "2024".
- Only include filters you can reasonably infer. Use null for unknowns.
- Keep the output minimal and valid JSON only.

Return ONLY valid JSON. Do not wrap it in markdown fences or add explanation."""


def _ollama_config() -> tuple[str, str, Optional[str]]:
    """Return (api_base, model, api_key)."""
    api_base = os.environ.get("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENWIKI_API_KEY")
    return api_base, model, api_key


async def _call_ollama_chat(messages: list[dict[str, str]]) -> dict:
    """Call the Ollama Chat API and return the parsed JSON content."""
    api_base, model, api_key = _ollama_config()
    url = f"{api_base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """Safely parse an ISO 8601 datetime string."""
    if not value:
        return None
    try:
        # Replace trailing Z with +00:00 for fromisoformat compatibility.
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _clamp_int(value: Optional[int], min_val: int, max_val: int) -> Optional[int]:
    """Clamp an integer value to a range, returning None if invalid."""
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return max(min_val, min(max_val, value))


def _build_search_query(raw_dict: dict, default_limit: int = 20, default_offset: int = 0) -> SearchQuery:
    """Convert a raw parsed dict into a validated SearchQuery."""
    text = raw_dict.get("text")
    if text is not None:
        text = str(text).strip() or None

    semantic = raw_dict.get("semantic")
    if semantic is not None:
        semantic = str(semantic).strip() or None

    raw_filters = raw_dict.get("filters") or {}
    if not isinstance(raw_filters, dict):
        raw_filters = {}

    tags = raw_filters.get("tags")
    if isinstance(tags, list):
        tags = [str(tag).lower()[:50] for tag in tags if tag]
        if not tags:
            tags = None
    else:
        tags = None

    filters = SearchFilters(
        date_range_start=_parse_iso_datetime(raw_filters.get("date_range_start")),
        date_range_end=_parse_iso_datetime(raw_filters.get("date_range_end")),
        tags=tags,
        mood=str(raw_filters.get("mood"))[:50] if raw_filters.get("mood") else None,
        importance_min=_clamp_int(raw_filters.get("importance_min"), 1, 10),
        importance_max=_clamp_int(raw_filters.get("importance_max"), 1, 10),
    )

    limit = _clamp_int(raw_dict.get("limit"), 1, 100)
    if limit is None:
        limit = default_limit

    offset = _clamp_int(raw_dict.get("offset"), 0, 10_000)
    if offset is None:
        offset = default_offset

    return SearchQuery(
        text=text,
        semantic=semantic,
        filters=filters,
        limit=limit,
        offset=offset,
    )


def _heuristic_parse(query: str) -> SearchQuery:
    """Fallback parser when the LLM fails. Handles basic time expressions."""
    query_lower = query.lower()
    now = datetime.utcnow()

    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None

    # Basic relative date handling.
    if "yesterday" in query_lower:
        yesterday = now - timedelta(days=1)
        date_range_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        date_range_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif "this week" in query_lower:
        start_of_week = now - timedelta(days=now.weekday())
        date_range_start = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        date_range_end = now
    elif "last month" in query_lower or "previous month" in query_lower:
        first_this_month = now.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        date_range_start = last_month_start.replace(hour=0, minute=0, second=0, microsecond=0)
        date_range_end = last_month_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif re.search(r"\bq1\b", query_lower):
        year = now.year
        date_range_start = datetime(year, 1, 1)
        date_range_end = datetime(year, 3, 31, 23, 59, 59)
    elif re.search(r"\bq2\b", query_lower):
        year = now.year
        date_range_start = datetime(year, 4, 1)
        date_range_end = datetime(year, 6, 30, 23, 59, 59)
    elif re.search(r"\bq3\b", query_lower):
        year = now.year
        date_range_start = datetime(year, 7, 1)
        date_range_end = datetime(year, 9, 30, 23, 59, 59)
    elif re.search(r"\bq4\b", query_lower):
        year = now.year
        date_range_start = datetime(year, 10, 1)
        date_range_end = datetime(year, 12, 31, 23, 59, 59)

    filters = SearchFilters(
        date_range_start=date_range_start,
        date_range_end=date_range_end,
    )

    # Use the whole query as text keywords, stripped of punctuation.
    text = re.sub(r"[^\w\s]", " ", query).strip()

    return SearchQuery(text=text, semantic=query, filters=filters, limit=20, offset=0)


async def parse_search_query(query: str) -> SearchQuery:
    """Parse a natural language query into a structured SearchQuery.

    Uses the Ollama Chat API with a JSON-mode prompt. Falls back to a
    heuristic parser if the LLM call fails or returns invalid output.
    """
    if not query or not query.strip():
        return SearchQuery(text=None, semantic=None, filters=None, limit=20, offset=0)

    try:
        messages = [
            {"role": "system", "content": SEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        raw_dict = await _call_ollama_chat(messages)
        return _build_search_query(raw_dict)
    except Exception:
        return _heuristic_parse(query)
