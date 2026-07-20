"""Story Agent: generate markdown narratives from selected memories."""

import json
import os
from typing import Optional

import httpx

DEFAULT_OLLAMA_API_BASE = "https://api.ollama.com"
DEFAULT_OLLAMA_MODEL = "glm-5.1"
DEFAULT_CLAUDE_MODEL = "claude-3-opus-20240229"
REQUEST_TIMEOUT_SECONDS = 30.0


STORY_SYSTEM_PROMPT = """You are the Story Agent for MEMIND.
Your job is to take a set of user memories and generate a coherent, readable markdown narrative.

Input fields:
- story_type: one of chronological, thematic, curated, digest
- memories: list of memories with title, summary, created_at, mood, tags
- custom_prompt: optional user instruction for tone/focus

Story type instructions:
- chronological: timeline narrative ("On [date]..., then..., finally...")
- thematic: theme-based ("The thread of [theme] connects these moments...")
- curated: highlight reel ("Here are your most meaningful memories...")
- digest: weekly/monthly recap ("This period, you experienced...")

Rules:
- Output valid markdown.
- Use transitions between memories.
- Do not invent facts not present in the memories.
- Keep the tone warm and reflective.
- Respect the custom_prompt if provided.
- The response should be a single markdown string under the key "narrative".

Return ONLY a JSON object with exactly this field:
- narrative: string (markdown)

Do not wrap it in markdown fences or add explanation outside the JSON."""


def _ollama_config() -> tuple[str, str, Optional[str]]:
    """Return (api_base, model, api_key)."""
    api_base = os.environ.get("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE).rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENWIKI_API_KEY")
    return api_base, model, api_key


def _claude_config() -> tuple[Optional[str], str]:
    """Return (api_key, model)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
    return api_key, model


async def _call_ollama_chat(messages: list[dict[str, str]]) -> dict:
    """Call the Ollama Chat API and return parsed JSON content."""
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


async def _call_claude_chat(messages: list[dict[str, str]]) -> dict:
    """Call the Anthropic Claude API and return parsed JSON content."""
    api_key, model = _claude_config()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    system_message = None
    user_messages = messages
    if messages and messages[0]["role"] == "system":
        system_message = messages[0]["content"]
        user_messages = messages[1:]

    payload = {
        "model": model,
        "max_tokens": 2048,
        "messages": user_messages,
    }
    if system_message:
        payload["system"] = system_message

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["content"][0]["text"]
    return json.loads(content)


def _build_story_prompt(story_type: str, memories: list[dict], custom_prompt: Optional[str]) -> str:
    prompt_data = {
        "story_type": story_type,
        "memories": memories,
    }
    if custom_prompt:
        prompt_data["custom_prompt"] = custom_prompt
    return json.dumps(prompt_data, indent=2, default=str)


def _extract_narrative(raw_dict: dict, fallback_title: str) -> str:
    narrative = raw_dict.get("narrative")
    if narrative and isinstance(narrative, str) and narrative.strip():
        return narrative.strip()
    return f"# {fallback_title}\n\nA story could not be generated from the selected memories."


def _quality_check_passes(narrative: str) -> bool:
    """Simple heuristic: narrative should be non-trivial markdown."""
    if not narrative:
        return False
    cleaned = narrative.strip()
    if len(cleaned) < 50:
        return False
    return True


async def generate_story(
    story_type: str,
    memories: list[dict],
    custom_prompt: Optional[str] = None,
) -> str:
    """Generate a markdown narrative from selected memories.

    Tries Ollama first. If the result is poor and Claude is configured, falls back to Claude.
    Returns a safe fallback markdown if both fail.
    """
    if not memories:
        return "# Story\n\nNo memories were provided to generate a story."

    messages = [
        {"role": "system", "content": STORY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_story_prompt(story_type, memories, custom_prompt)},
    ]

    try:
        raw_dict = await _call_ollama_chat(messages)
        narrative = _extract_narrative(raw_dict, "Story")
        if _quality_check_passes(narrative):
            return narrative
    except Exception:
        narrative = ""

    # Fallback to Claude if Ollama failed or returned poor output.
    claude_key, _ = _claude_config()
    if claude_key:
        try:
            raw_dict = await _call_claude_chat(messages)
            return _extract_narrative(raw_dict, "Story")
        except Exception:
            pass

    if narrative:
        return narrative

    return _fallback_story(story_type, memories)


def _fallback_story(story_type: str, memories: list[dict]) -> str:
    """Produce a minimal safe narrative when all LLM calls fail."""
    title = story_type.replace("_", " ").title()
    lines = [f"# {title} Story", ""]

    if story_type == "chronological":
        lines.append("Here are the memories in chronological order:")
    elif story_type == "thematic":
        lines.append("These memories connect around common themes:")
    elif story_type == "curated":
        lines.append("Here are your selected memories:")
    else:
        lines.append("Here is a recap of your selected memories:")

    for mem in memories:
        title = mem.get("title") or "Memory"
        summary = mem.get("summary") or ""
        created_at = mem.get("created_at") or ""
        lines.append(f"\n## {title}")
        if created_at:
            lines.append(f"*{created_at}*")
        if summary:
            lines.append(summary)

    return "\n".join(lines)
