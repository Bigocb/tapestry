"""Tests for the one place that talks to a model provider.

Every agent used to carry its own copy of the same OpenAI-compatible HTTP call.
This is that call, once, driven by the resolved per-user settings. It stays thin
on purpose: OpenAI-compatible providers share one shape, Anthropic differs, and
both are covered here.
"""

import pytest

from app.agents import llm
from app.llm_config import LLMConfig


def cfg(**overrides) -> LLMConfig:
    base = dict(
        role="capture",
        provider="openai",
        model="gpt-4o-mini",
        api_base=None,
        api_key="sk-test",
    )
    base.update(overrides)
    return LLMConfig(**base)


class TestOpenAICompatible:
    @pytest.mark.asyncio
    async def test_a_chat_returns_the_message_content(self, monkeypatch):
        seen = {}

        async def fake_post(url, headers, payload):
            seen["url"] = url
            seen["headers"] = headers
            seen["payload"] = payload
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        result = await llm.chat_json(cfg(), [{"role": "user", "content": "hi"}])

        assert result == {"ok": True}
        assert seen["url"] == "https://api.openai.com/v1/chat/completions"
        assert seen["headers"]["Authorization"] == "Bearer sk-test"
        assert seen["payload"]["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_a_self_hosted_base_url_is_used_as_given(self, monkeypatch):
        seen = {}

        async def fake_post(url, headers, payload):
            seen["url"] = url
            return {"choices": [{"message": {"content": "{}"}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        await llm.chat_json(
            cfg(provider="ollama", api_base="http://localhost:11434/v1"), []
        )

        assert seen["url"] == "http://localhost:11434/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_a_bare_base_url_gets_the_version_suffix(self, monkeypatch):
        seen = {}

        async def fake_post(url, headers, payload):
            seen["url"] = url
            return {"choices": [{"message": {"content": "{}"}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        await llm.chat_json(cfg(provider="ollama", api_base="http://host:11434"), [])

        assert seen["url"] == "http://host:11434/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_no_key_means_no_authorization_header(self, monkeypatch):
        seen = {}

        async def fake_post(url, headers, payload):
            seen["headers"] = headers
            return {"choices": [{"message": {"content": "{}"}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        await llm.chat_json(cfg(api_key=None), [])

        assert "Authorization" not in seen["headers"]

    @pytest.mark.asyncio
    async def test_markdown_fences_are_stripped(self, monkeypatch):
        async def fake_post(url, headers, payload):
            return {
                "choices": [
                    {"message": {"content": '```json\n{"a": 1}\n```'}}
                ]
            }

        monkeypatch.setattr(llm, "_post_json", fake_post)

        assert await llm.chat_json(cfg(), []) == {"a": 1}


class TestAnthropic:
    @pytest.mark.asyncio
    async def test_it_uses_the_anthropic_shape(self, monkeypatch):
        seen = {}

        async def fake_post(url, headers, payload):
            seen["url"] = url
            seen["headers"] = headers
            seen["payload"] = payload
            return {"content": [{"type": "text", "text": '{"ok": true}'}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        result = await llm.chat_json(
            cfg(provider="anthropic", model="claude-3-5-haiku-latest"),
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ],
        )

        assert result == {"ok": True}
        assert seen["headers"]["x-api-key"] == "sk-test"
        assert "anthropic-version" in seen["headers"]
        # The system prompt is a top-level field, not a message.
        assert seen["payload"]["system"] == "be brief"
        assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]


class TestEmbeddings:
    @pytest.mark.asyncio
    async def test_it_returns_floats(self, monkeypatch):
        async def fake_post(url, headers, payload):
            return {"data": [{"embedding": [0.1, 0.2, "0.3"]}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)

        vector = await llm.embed(cfg(model="text-embedding-3-small"), "hello")

        assert vector == [0.1, 0.2, 0.3]


class TestConfigForRole:
    @pytest.mark.asyncio
    async def test_with_no_context_the_environment_default_is_used(self):
        resolved = await llm.config_for_role("capture")

        assert resolved.provider == "ollama"
        assert resolved.model


@pytest.mark.asyncio
async def test_http_errors_are_raised(monkeypatch):
    import httpx

    class Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return httpx.Response(
                401,
                json={"error": "bad key"},
                request=httpx.Request("POST", "https://x/v1/chat/completions"),
            )

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: Boom())

    with pytest.raises(httpx.HTTPStatusError):
        await llm.chat_json(cfg(), [{"role": "user", "content": "hi"}])
