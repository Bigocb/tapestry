"""Tests for embedding generation and semantic search."""

import pytest

from app.agents.embeddings import (
    _fallback_embedding,
    cosine_similarity,
    deserialize_embedding,
    generate_embedding,
    serialize_embedding,
)


class TestEmbeddingSerialization:
    """Unit tests for embedding serialization helpers."""

    def test_serialize_and_deserialize_embedding(self):
        embedding = [0.1, 0.2, 0.3, 0.4]
        serialized = serialize_embedding(embedding)
        deserialized = deserialize_embedding(serialized)
        assert deserialized == embedding

    def test_deserialize_embedding_returns_empty_for_none(self):
        assert deserialize_embedding(None) == []

    def test_deserialize_embedding_returns_empty_for_invalid_json(self):
        assert deserialize_embedding("not-json") == []


class TestCosineSimilarity:
    """Unit tests for cosine similarity."""

    def test_identical_vectors_have_similarity_one(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_have_similarity_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_different_length_vectors_return_zero(self):
        assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0

    def test_empty_vectors_return_zero(self):
        assert cosine_similarity([], [1.0]) == 0.0


class TestFallbackEmbedding:
    """Unit tests for deterministic fallback embeddings."""

    def test_fallback_embedding_is_normalized(self):
        emb = _fallback_embedding("some text")
        norm = sum(v * v for v in emb) ** 0.5
        assert norm == pytest.approx(1.0)

    def test_fallback_embedding_is_deterministic(self):
        a = _fallback_embedding("deterministic text")
        b = _fallback_embedding("deterministic text")
        assert a == b

    def test_fallback_embeddings_for_different_texts_are_different(self):
        a = _fallback_embedding("text a")
        b = _fallback_embedding("text b")
        assert a != b

    def test_fallback_embedding_dimension_defaults_to_384(self):
        emb = _fallback_embedding("x")
        assert len(emb) == 384


class TestGenerateEmbedding:
    """Integration-ish tests for generate_embedding with mocked Ollama."""

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_llm_embedding(self, monkeypatch):
        async def fake_call(text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

        monkeypatch.setattr("app.agents.embeddings._call_ollama_embeddings", fake_call)
        result = await generate_embedding("hello world")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_generate_embedding_falls_back_on_error(self, monkeypatch):
        async def failing_call(text: str) -> list[float]:
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr(
            "app.agents.embeddings._call_ollama_embeddings", failing_call
        )
        result = await generate_embedding("hello world")
        assert len(result) == 384
        norm = sum(v * v for v in result) ** 0.5
        assert norm == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_empty_for_empty_input(self):
        assert await generate_embedding("") == []
        assert await generate_embedding("   ") == []
