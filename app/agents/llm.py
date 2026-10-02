"""The one place that talks to a model provider.

Every agent used to carry its own copy of the same OpenAI-compatible HTTP call,
each re-reading the environment. This is that call, once, driven by the resolved
per-user settings.

Two shapes are covered, because they are the two that matter here:
OpenAI-compatible (OpenAI, Ollama, Groq, OpenRouter, a self-hosted server) and
Anthropic. Adding a provider that speaks either shape is a base URL and a model
name, not code.

The adapter is deliberately thin. It returns parsed JSON for chat and a list of
floats for embeddings, and raises on failure so each caller keeps its own
deterministic fallback.
"""

from __future__ import annotations

import json
from typing import Optional, Sequence

import httpx

from app.llm_config import LLMConfig, env_default

REQUEST_TIMEOUT_SECONDS = 30.0

# Where each known provider lives, when the user has not overridden the base.
_PROVIDER_BASE = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "https://ollama.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
}

_ANTHROPIC_VERSION = "2023-06-01"


def _base_url(config: LLMConfig) -> str:
    """The API root for a config, with the /v1 suffix where the shape wants it."""
    if config.api_base:
        return config.api_base.rstrip("/")
    return _PROVIDER_BASE.get(config.provider, _PROVIDER_BASE["openai"])


async def _post_json(url: str, headers: dict, payload: dict) -> dict:
    """POST JSON and return the parsed body, raising on a bad status."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in markdown fences despite being asked not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    if text.endswith("```"):
        text = text.rsplit("\n", 1)[0]
    return text.strip()


def _openai_messages(
    messages: Sequence[dict],
) -> tuple[list[dict], Optional[str]]:
    """Split a system message out for Anthropic, leave the rest alone."""
    system = None
    chat = []
    for message in messages:
        if message.get("role") == "system":
            system = message.get("content")
        else:
            chat.append(message)
    return chat, system


async def chat_json(config: LLMConfig, messages: Sequence[dict]) -> dict:
    """Ask for a JSON object and return it parsed.

    Raises on any failure — network, status or unparseable content — so the
    caller can fall back to its deterministic path rather than half-working.
    """
    if config.provider == "anthropic":
        chat, system = _openai_messages(messages)
        payload = {
            "model": config.model,
            "max_tokens": 4096,
            "messages": chat,
        }
        if system:
            payload["system"] = system
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": _ANTHROPIC_VERSION,
        }
        if config.api_key:
            headers["x-api-key"] = config.api_key
        body = await _post_json(
            f"{_base_url(config)}/messages", headers, payload
        )
        parts = body.get("content") or []
        content = "".join(
            part.get("text", "") for part in parts if part.get("type") == "text"
        )
        return json.loads(_strip_fences(content))

    base = _base_url(config)
    # OpenAI-compatible roots already end in /v1; only add it for a bare host
    # (a self-hosted Ollama, say).
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    payload = {
        "model": config.model,
        "messages": list(messages),
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    body = await _post_json(f"{base}/chat/completions", headers, payload)
    content = body["choices"][0]["message"]["content"]
    return json.loads(_strip_fences(content))


async def embed(config: LLMConfig, text: str) -> list[float]:
    """Return an embedding vector for one piece of text."""
    base = _base_url(config)
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = await _post_json(
        f"{base}/embeddings",
        headers,
        {"model": config.model, "input": text},
    )
    return [float(value) for value in body["data"][0]["embedding"]]


# ---------------------------------------------------------------------------
# Config for a role.
#
# Reading the database is asynchronous and the agents call synchronously-shaped
# code, so the caller resolves the config once (it knows the user) and sets it
# for the duration of one agent call. With nothing set, the environment default
# applies — which is exactly the old behaviour, and what tests rely on.
# ---------------------------------------------------------------------------
import contextvars
from contextlib import asynccontextmanager

_config_override: contextvars.ContextVar[Optional[LLMConfig]] = (
    contextvars.ContextVar("llm_config_override", default=None)
)


def set_config(config: Optional[LLMConfig]) -> contextvars.Token:
    """Use ``config`` for agent calls on this task until the token is reset."""
    return _config_override.set(config)


def reset_config(token: contextvars.Token) -> None:
    _config_override.reset(token)


@asynccontextmanager
async def using(db, user_id: str, role: str):
    """Run an agent call with the user's settings for that role.

    The agents read the current config themselves, so a caller only has to wrap
    the call. Resolving here — where the user is known — is what keeps one
    person's model and key from being used for another's work.
    """
    from app.llm_config import resolve

    config = await resolve(db, user_id, role)
    token = set_config(config)
    try:
        yield config
    finally:
        reset_config(token)


async def config_for_role(role: str) -> LLMConfig:
    """The config an agent call should use right now."""
    override = _config_override.get()
    if override is not None:
        return override
    return env_default(role)
