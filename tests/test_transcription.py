"""Tests for local Whisper voice transcription.

The transcription implementation delegates to ``faster-whisper``. Tests never
load a real model: they monkeypatch the model loader, so the suite stays fast
and needs no download.

Behaviour under test:
- lazy, cached model loading (the model is expensive; load once)
- decoding happens off the event loop (it is CPU-bound and blocking)
- a missing dependency gives a clear 501 rather than a 500
- empty audio is rejected with 400
- the model name is configurable via environment
"""

import pytest
from fastapi import HTTPException

from app.routes import memories as routes


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeModel:
    """Stands in for a WhisperModel."""

    def __init__(self, texts):
        self.texts = texts
        self.calls = []

    def transcribe(self, audio, beam_size=1):
        self.calls.append(audio)
        segments = [FakeSegment(t) for t in self.texts]
        info = type("Info", (), {"language": "en"})()
        return segments, info


@pytest.fixture(autouse=True)
def reset_model_cache():
    """Keep the module-level model cache from leaking between tests."""
    routes._whisper_model_cache.clear()
    yield
    routes._whisper_model_cache.clear()


class TestTranscribeAudio:
    @pytest.mark.asyncio
    async def test_returns_joined_segment_text(self, monkeypatch):
        model = FakeModel(["Hello there.", " This is a memory."])

        def fake_load(model_name):
            return model

        monkeypatch.setattr(routes, "_get_whisper_model", fake_load)

        result = await routes._transcribe_audio(b"audio-bytes")

        assert result == "Hello there. This is a memory."

    @pytest.mark.asyncio
    async def test_strips_surrounding_whitespace(self, monkeypatch):
        model = FakeModel(["  spaced out  "])
        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: model)

        result = await routes._transcribe_audio(b"audio-bytes")

        assert result == "spaced out"

    @pytest.mark.asyncio
    async def test_empty_transcription_raises_400(self, monkeypatch):
        """A recording with no speech should be a client error, not silent empty text."""
        model = FakeModel([])
        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: model)

        with pytest.raises(HTTPException) as exc:
            await routes._transcribe_audio(b"audio-bytes")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_only_transcription_raises_400(self, monkeypatch):
        model = FakeModel(["   ", "\n"])
        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: model)

        with pytest.raises(HTTPException) as exc:
            await routes._transcribe_audio(b"audio-bytes")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_audio_raises_400(self, monkeypatch):
        model = FakeModel(["should not be reached"])
        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: model)

        with pytest.raises(HTTPException) as exc:
            await routes._transcribe_audio(b"")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_model_load_failure_raises_501(self, monkeypatch):
        """A missing dependency or unavailable model is a server-side setup problem."""

        def boom(model_name):
            raise ImportError("No module named 'faster_whisper'")

        monkeypatch.setattr(routes, "_get_whisper_model", boom)

        with pytest.raises(HTTPException) as exc:
            await routes._transcribe_audio(b"audio-bytes")

        assert exc.value.status_code == 501

    @pytest.mark.asyncio
    async def test_transcription_failure_raises_500(self, monkeypatch):
        class BrokenModel:
            def transcribe(self, audio, beam_size=1):
                raise RuntimeError("decoder exploded")

        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: BrokenModel())

        with pytest.raises(HTTPException) as exc:
            await routes._transcribe_audio(b"audio-bytes")

        assert exc.value.status_code == 500


class TestModelCaching:
    @pytest.mark.asyncio
    async def test_model_is_loaded_once_and_reused(self, monkeypatch):
        """Loading Whisper is expensive, so it must be cached across calls.

        Patches the *uncached* loader so the real cache is exercised.
        """
        model = FakeModel(["hi"])
        loads = {"count": 0}

        def counting_load(model_name):
            loads["count"] += 1
            return model

        monkeypatch.setattr(routes, "_load_whisper_model", counting_load)

        await routes._transcribe_audio(b"one")
        await routes._transcribe_audio(b"two")

        assert loads["count"] == 1

    @pytest.mark.asyncio
    async def test_different_models_use_separate_cache_entries(self, monkeypatch):
        models = {"tiny": FakeModel(["tiny text"]), "base": FakeModel(["base text"])}

        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: models[name])
        monkeypatch.setattr(routes, "_whisper_model_name", lambda: "tiny")
        first = await routes._transcribe_audio(b"a")

        monkeypatch.setattr(routes, "_whisper_model_name", lambda: "base")
        second = await routes._transcribe_audio(b"b")

        assert first == "tiny text"
        assert second == "base text"


class TestAudioHandling:
    """Regression: faster-whisper decodes from a path, not raw bytes.

    Passing bytes straight to `model.transcribe` raised
    "File object has no read() method", which surfaced as a 500 on the voice
    endpoint. The upload must be spooled to a temporary file first.
    """

    def test_audio_is_written_to_a_path_not_passed_as_bytes(self, monkeypatch):
        from app.routes import memories as routes

        seen = {}

        class PathCheckingModel:
            def transcribe(self, audio, beam_size=1):
                # The decoder needs a path or file-like object, never bytes.
                seen["type"] = type(audio).__name__
                seen["exists"] = isinstance(audio, str) and __import__("os").path.exists(audio)
                return [], type("I", (), {"language": "en"})()

        monkeypatch.setattr(
            routes, "_get_whisper_model", lambda name: PathCheckingModel()
        )

        routes._transcribe_sync(b"RIFF....WAVEfake-audio")

        assert seen["type"] == "str", "audio must be handed over as a path"
        assert seen["exists"] is True, "the temp file must exist during decoding"

    def test_temp_file_is_cleaned_up(self, monkeypatch):
        import glob
        import os
        import tempfile

        from app.routes import memories as routes

        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.wav")))

        class OkModel:
            def transcribe(self, audio, beam_size=1):
                return [FakeSegment("hi")], type("I", (), {"language": "en"})()

        monkeypatch.setattr(routes, "_get_whisper_model", lambda name: OkModel())
        routes._transcribe_sync(b"RIFF....WAVEfake-audio")

        after = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.wav")))
        assert after == before, "temporary audio file should be removed"

    def test_suffix_detection(self):
        from app.routes.memories import _audio_suffix

        assert _audio_suffix(b"RIFF\x00\x00\x00\x00WAVEfmt ") == ".wav"
        assert _audio_suffix(b"ID3\x03\x00\x00\x00") == ".mp3"
        assert _audio_suffix(b"\x00\x00\x00\x20ftypM4A ") == ".m4a"
        assert _audio_suffix(b"OggS\x00\x02") == ".ogg"
        assert _audio_suffix(b"\x1aE\xdf\xa3webm") == ".webm"
        # Unknown headers fall back to the browser recorder's format.
        assert _audio_suffix(b"garbage") == ".webm"


class TestModelNameConfig:
    def test_default_model_name(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL", raising=False)
        assert routes._whisper_model_name() == "base"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL", "small")
        assert routes._whisper_model_name() == "small"
