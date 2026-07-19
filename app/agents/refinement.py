"""Refinement Agent: resolve ambiguities and normalize a structured memory."""

import json
import os
from typing import Any, Optional

import httpx

from app.models.schemas import EntityData, StructuredMemory

DEFAULT_OLLAMA_API_BASE = "https://api.ollama.com"
DEFAULT_OLLAMA_MODEL = "glm-5.1"
REQUEST_TIMEOUT_SECONDS = 8.0


REFINEMENT_SYSTEM_PROMPT = """You are the Refinement Agent for MEMIND.
Your job is to take a structured memory and, using the user's recent memories as context, resolve ambiguities and normalize entities.

Input fields:
- raw_input: the original raw text
- structured_content: current title, summary, entities, mood, importance_level, initial_tags
- recent_memories: list of recent memory summaries for context

Tasks:
1. Resolve vague references like "that meeting", "her", "last week" into specific names/dates/events when possible using recent_memories.
2. Normalize dates to ISO 8601 where a specific date is implied (e.g. "2024-07-15").
3. Keep the title concise (3-12 words).
4. Keep the summary 1-3 sentences.
5. Do not invent facts that are not supported by the raw input or recent memories.

Output a single JSON object with exactly these fields:
- title: string
- summary: string
- entities: list of objects with keys type, value, optional metadata
- mood: string or null
- importance_level: integer 1-10
- initial_tags: list of lowercase string tags

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


def _build_refinement_prompt(
    raw_input: str,
    structured_content: dict[str, Any],
    recent_memories: list[dict[str, Any]],
) -> str:
    prompt_data = {
        "raw_input": raw_input,
        "structured_content": structured_content,
        "recent_memories": recent_memories,
    }
    return json.dumps(prompt_data, indent=2, default=str)


def _normalize_entities(raw_entities: list[dict]) -> list[EntityData]:
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


def _build_structured_memory(raw_dict: dict, fallback: StructuredMemory) -> StructuredMemory:
    """Safely build StructuredMemory from LLM output, falling back on missing fields."""
    title = str(raw_dict.get("title") or "")
    if not title:
        title = fallback.title

    summary = str(raw_dict.get("summary") or "")
    if not summary:
        summary = fallback.summary

    mood = raw_dict.get("mood")
    if mood is not None:
        mood = str(mood)[:50] or fallback.mood
    else:
        mood = fallback.mood

    importance_level = raw_dict.get("importance_level")
    try:
        importance_level = int(importance_level)
    except (TypeError, ValueError):
        importance_level = fallback.importance_level
    importance_level = max(1, min(10, importance_level))

    raw_entities = raw_dict.get("entities") or []
    if not isinstance(raw_entities, list):
        raw_entities = []
    entities = _normalize_entities(raw_entities) or fallback.entities

    raw_tags = raw_dict.get("initial_tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    initial_tags = [str(tag).lower()[:50] for tag in raw_tags if tag] or fallback.initial_tags

    return StructuredMemory(
        title=title,
        summary=summary,
        entities=entities,
        mood=mood,
        importance_level=importance_level,
        initial_tags=initial_tags,
    )


def _structured_memory_from_dict(data: dict[str, Any]) -> StructuredMemory:
    """Convert a memory's structured_content dict into a StructuredMemory, tolerating missing fields."""
    if not isinstance(data, dict):
        data = {}

    raw_entities = data.get("entities") or []
    entities = _normalize_entities(raw_entities) if isinstance(raw_entities, list) else []

    importance_level = data.get("importance_level")
    try:
        importance_level = int(importance_level)
    except (TypeError, ValueError):
        importance_level = 5
    importance_level = max(1, min(10, importance_level))

    raw_tags = data.get("initial_tags") or []
    initial_tags = [str(tag).lower()[:50] for tag in raw_tags if tag] if isinstance(raw_tags, list) else []

    return StructuredMemory(
        title=str(data.get("title") or "Untitled")[:255],
        summary=str(data.get("summary") or "") or "No summary available",
        entities=entities,
        mood=str(data.get("mood"))[:50] if data.get("mood") else None,
        importance_level=importance_level,
        initial_tags=initial_tags,
    )


async def refine_memory(
    raw_input: str,
    structured_content: dict[str, Any],
    recent_memories: list[dict[str, Any]],
) -> StructuredMemory:
    """Refine a structured memory using recent memories as context.

    On LLM failure, returns a StructuredMemory built from the existing
    structured_content so the pipeline can continue.
    """
    current = _structured_memory_from_dict(structured_content)

    if not raw_input or not raw_input.strip():
        return current

    try:
        messages = [
            {"role": "system", "content": REFINEMENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_refinement_prompt(raw_input, structured_content, recent_memories),
            },
        ]
        raw_dict = await _call_ollama_chat(messages)
        return _build_structured_memory(raw_dict, current)
    except Exception:
        return current
