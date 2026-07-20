"""Embedding generation and similarity search utilities."""

import json
import math
import os
from typing import Optional

import httpx

DEFAULT_OLLAMA_API_BASE = "https://api.ollama.com"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"
REQUEST_TIMEOUT_SECONDS = 10.0


def _ollama_config() -> tuple[str, str, Optional[str]]:
    """Return (api_base, model, api_key)."""
    api_base = os.environ.get("OLLAMA_API_BASE", DEFAULT_OLLAMA_API_BASE).rstrip("/")
    model = os.environ.get("OLLAMA_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL)
    api_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENWIKI_API_KEY")
    return api_base, model, api_key


async def _call_ollama_embeddings(text: str) -> list[float]:
    """Call the Ollama embeddings API and return the embedding vector."""
    api_base, model, api_key = _ollama_config()
    url = f"{api_base}/v1/embeddings"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "input": text,
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    # Ollama embeddings endpoint returns embedding in data[0].embedding.
    embedding = data["data"][0]["embedding"]
    return [float(x) for x in embedding]


async def generate_embedding(text: str) -> list[float]:
    """Generate a vector embedding for the given text via Ollama embeddings API.

    Falls back to a simple deterministic hash-based embedding if the API call
    fails. This keeps local dev/tests working without a live Ollama service.
    """
    if not text or not text.strip():
        return []

    try:
        return await _call_ollama_embeddings(text)
    except Exception:
        return _fallback_embedding(text)


def _fallback_embedding(text: str, dimension: int = 384) -> list[float]:
    """Produce a deterministic, normalized pseudo-embedding for offline use."""
    import hashlib

    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for i in range(dimension):
        # Use pairs of bytes to generate values in [-1, 1].
        byte_a = seed[i % len(seed)]
        byte_b = seed[(i + 1) % len(seed)]
        value = ((byte_a + byte_b) / 510.0) - 1.0
        values.append(value)

    # Normalize to unit length.
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        return values
    return [v / norm for v in values]


def serialize_embedding(embedding: list[float]) -> str:
    """Serialize an embedding to a JSON string for storage."""
    return json.dumps(embedding)


def deserialize_embedding(stored: Optional[str]) -> list[float]:
    """Deserialize a stored embedding JSON string back to a list of floats."""
    if not stored:
        return []
    try:
        return [float(x) for x in json.loads(stored)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
