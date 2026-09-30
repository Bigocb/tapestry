"""Enrichment Agent: suggest tags, importance, and related memory links."""

import json
import os
from datetime import datetime
from typing import Any, Optional

import httpx

from app.models.schemas import StructuredMemory

DEFAULT_OLLAMA_API_BASE = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL = "gemma4:31b"
REQUEST_TIMEOUT_SECONDS = 30.0


ENRICHMENT_SYSTEM_PROMPT = """You are the Enrichment Agent for Tapestry.
Your job is to take a refined memory and up to 5 similar past memories, then suggest better metadata and thematic links.

Input fields:
- memory: the refined memory with title, summary, entities, mood, importance_level, initial_tags, event_date
- similar_memories: list of related memories with title, summary, score, memory_id

Tasks:
1. Suggest a final list of 1-8 lowercase tags that best categorize the memory, informed by similar memories.
2. Confirm or adjust importance_level (1-10). Use similar memories as context for calibration.
3. Identify which of the similar memories are thematically related enough to link. Return their memory_ids in related_memory_ids.
4. Keep the title, summary, entities, mood, and event_date unchanged unless you can clearly improve them.

Output a single JSON object with exactly these fields:
- title: string (unchanged unless improved)
- summary: string (unchanged unless improved)
- entities: list of objects with keys type, value, optional metadata
- mood: string or null
- importance_level: integer 1-10
- initial_tags: list of lowercase string tags
- event_date: ISO 8601 datetime string or null
- related_memory_ids: list of UUID strings from the similar_memories input

Allowed entity types: person, place, date, event, concept.

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
        "messages": messages,
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
    if content.endswith("```"):
        content = content.rsplit("\n", 1)[0]
    content = content.strip()
    return json.loads(content)


def _build_enrichment_prompt(
    memory: dict[str, Any], similar_memories: list[dict[str, Any]]
) -> str:
    prompt_data = {
        "memory": memory,
        "similar_memories": similar_memories,
    }
    return json.dumps(prompt_data, indent=2, default=str)


def _validate_uuid(value: Any) -> Optional[str]:
    """Return a string UUID if valid, otherwise None."""
    from uuid import UUID as UUID_TYPE

    if value is None:
        return None
    try:
        if isinstance(value, UUID_TYPE):
            return str(value)
        return str(UUID_TYPE(str(value)))
    except (ValueError, TypeError):
        return None


def _parse_event_date(value: Any, fallback: Optional[datetime]) -> Optional[datetime]:
    """Parse an ISO datetime string or return the fallback."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def _sanitize_enrichment_output(
    raw_dict: dict,
    current: StructuredMemory,
    candidate_ids: set[str],
) -> StructuredMemory:
    """Build a StructuredMemory from the LLM response, keeping current values as fallback."""
    title = str(raw_dict.get("title") or current.title)[:255]
    summary = str(raw_dict.get("summary") or current.summary)
    mood = raw_dict.get("mood")
    if mood is not None:
        mood = str(mood)[:50] or current.mood
    else:
        mood = current.mood

    importance_level = raw_dict.get("importance_level")
    try:
        importance_level = int(importance_level)
    except (TypeError, ValueError):
        importance_level = current.importance_level
    importance_level = max(1, min(10, importance_level))

    raw_tags = raw_dict.get("initial_tags") or []
    if isinstance(raw_tags, list):
        initial_tags = [
            str(tag).lower()[:50] for tag in raw_tags if tag
        ] or current.initial_tags
    else:
        initial_tags = current.initial_tags

    raw_entities = raw_dict.get("entities") or []
    from app.agents.capture import _normalize_entities

    entities = (
        _normalize_entities(raw_entities)
        if isinstance(raw_entities, list)
        else current.entities
    )

    event_date = _parse_event_date(raw_dict.get("event_date"), current.event_date)

    # Carry fuzzy-period information through enrichment; otherwise a decade or
    # range would be flattened to a point date and its label lost.
    date_precision = str(raw_dict.get("date_precision") or current.date_precision or "") or None
    date_label = str(raw_dict.get("date_label") or current.date_label or "")[:120] or None
    event_date_end = _parse_event_date(
        raw_dict.get("event_date_end"), current.event_date_end
    )

    return StructuredMemory(
        title=title,
        summary=summary,
        entities=entities,
        mood=mood,
        importance_level=importance_level,
        initial_tags=initial_tags,
        event_date=event_date,
        date_precision=date_precision,
        event_date_end=event_date_end,
        date_label=date_label,
    )


def _parse_related_memory_ids(raw_dict: dict, candidate_ids: set[str]) -> list[str]:
    """Extract valid related memory IDs that were provided as candidates."""
    raw_ids = raw_dict.get("related_memory_ids") or []
    if not isinstance(raw_ids, list):
        return []

    valid = []
    for item in raw_ids:
        parsed = _validate_uuid(item)
        if parsed and parsed in candidate_ids:
            valid.append(parsed)
    return valid


async def enrich_memory(
    memory: dict[str, Any],
    similar_memories: list[dict[str, Any]],
) -> tuple[StructuredMemory, list[str]]:
    """Enrich a memory using similar memories as RAG context.

    Returns:
        A tuple of (enriched StructuredMemory, list of related memory IDs).
    """
    from app.agents.refinement import _structured_memory_from_dict

    current = _structured_memory_from_dict(memory)
    candidate_ids = {
        str(m.get("memory_id")) for m in similar_memories if m.get("memory_id")
    }

    try:
        messages = [
            {"role": "system", "content": ENRICHMENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_enrichment_prompt(memory, similar_memories),
            },
        ]
        raw_dict = await _call_ollama_chat(messages)
        enriched = _sanitize_enrichment_output(raw_dict, current, candidate_ids)
        related_ids = _parse_related_memory_ids(raw_dict, candidate_ids)
        return enriched, related_ids
    except Exception:
        return current, []
