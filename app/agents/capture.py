"""Capture Agent: turn raw memory input into structured StructuredMemory."""

import json
import os
from typing import Optional

import httpx

from app.models.schemas import EntityData, StructuredMemory

DEFAULT_OLLAMA_API_BASE = "https://ollama.com/v1"
DEFAULT_OLLAMA_MODEL = "llama3.2"
REQUEST_TIMEOUT_SECONDS = 30.0


CAPTURE_SYSTEM_PROMPT = """You are the Capture Agent for MEMIND, a memory-capture system.
Your job is to take a user's raw memory input and return a concise structured JSON object.
Do NOT resolve ambiguities (e.g., leave "that meeting" as-is). Do NOT add information you cannot infer from the input.

Output a single JSON object with exactly these fields:
- title: string, 3-12 words
- summary: string, 1-3 sentences
- entities: list of objects with keys type, value, and optional metadata
- mood: string or null (a single word describing the feeling, e.g. happy, anxious, excited)
- importance_level: integer 1-10
- initial_tags: list of lowercase string tags, 1-5 items

Allowed entity types: person, place, date, event, concept.

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


def _fallback_structured_memory(raw_input: str) -> StructuredMemory:
    """Produce a safe fallback when the LLM fails."""
    return StructuredMemory(
        title=raw_input[:100] if len(raw_input) <= 100 else raw_input[:97] + "...",
        summary=raw_input,
        entities=[],
        mood=None,
        importance_level=5,
        initial_tags=[],
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

    return StructuredMemory(
        title=title,
        summary=summary,
        entities=entities,
        mood=mood,
        importance_level=importance_level,
        initial_tags=initial_tags,
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
