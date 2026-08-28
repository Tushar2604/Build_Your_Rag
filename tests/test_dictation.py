"""Unit tests for dictation (speech-to-text).

Two things here are easy to get silently wrong. The provider/model pair must
resolve together — falling back on the key alone would POST Groq's model id to
OpenAI, which fails with a confusing 400 rather than an obvious one. And every
failure path must return a readable reason, because the mic button shows that
string verbatim and "something went wrong" next to a field the user just spoke
into is the worst possible outcome.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from src.config.settings import Settings
from src.infrastructure.voice.transcription import WhisperTranscriber


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "jwt_secret": "x" * 32,
        "groq_api_key": "",
        "openai_api_key": "",
    }
    return Settings(**{**base, **overrides})


# --- Provider / model resolution ---


def test_the_preferred_provider_wins_when_its_key_is_present() -> None:
    s = _settings(stt_provider="groq", groq_api_key="gk", openai_api_key="ok")
    assert s.resolve_stt() == ("groq", "gk")

    s = _settings(stt_provider="openai", groq_api_key="gk", openai_api_key="ok")
    assert s.resolve_stt() == ("openai", "ok")


def test_it_falls_back_to_whichever_provider_actually_has_a_key() -> None:
    # Dictation rides on keys the deployment already has; going dark because
    # STT_PROVIDER named the unconfigured one would be a pointless failure.
    s = _settings(stt_provider="groq", groq_api_key="", openai_api_key="ok")
    assert s.resolve_stt() == ("openai", "ok")


def test_no_keys_means_disabled_rather_than_a_half_configured_provider() -> None:
    s = _settings(groq_api_key="", openai_api_key="")
    assert s.resolve_stt() == ("", "")
    assert s.stt_enabled is False


def test_a_fallback_does_not_carry_the_other_vendors_model_id() -> None:
    # The actual bug this guards: STT_MODEL is a Groq model name, the key is
    # OpenAI's, and the request 400s on an unknown model.
    s = _settings(stt_provider="groq", groq_api_key="", openai_api_key="ok")
    provider, _ = s.resolve_stt()
    assert provider == "openai"
    assert s.stt_model_for(provider) == "whisper-1"


def test_an_explicit_model_applies_to_the_provider_it_was_set_for() -> None:
    s = _settings(stt_provider="groq", stt_model="whisper-large-v3", groq_api_key="gk")
    assert s.stt_model_for("groq") == "whisper-large-v3"
    # ...but not to the other vendor, which has never heard of it.
    assert s.stt_model_for("openai") == "whisper-1"


def test_the_adapter_reports_the_resolved_pair() -> None:
    t = WhisperTranscriber(_settings(stt_provider="groq", groq_api_key="gk"))
    assert t.enabled is True
    assert (t.provider, t.model) == ("groq", "whisper-large-v3-turbo")


# --- Failure paths ---


class _Resp:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _client_returning(resp, sink: dict | None = None):
    class _Client:
        async def post(self, url, headers=None, files=None, data=None):
            if sink is not None:
                sink.update(url=url, headers=headers, files=files, data=data)
            if isinstance(resp, Exception):
                raise resp
            return resp

    async def _get_client(*_a, **_k):
        return _Client()

    return _get_client


@pytest.fixture
def patched(monkeypatch):
    def _apply(resp, sink=None):
        monkeypatch.setattr(
            "src.infrastructure.voice.transcription.get_client",
            _client_returning(resp, sink),
        )
    return _apply


def _run(transcriber, audio=b"x" * 5000):
    return asyncio.run(transcriber.transcribe(audio))


def test_a_disabled_transcriber_explains_itself_instead_of_raising() -> None:
    ok, text, error = _run(WhisperTranscriber(_settings()))
    assert ok is False and text == ""
    assert "GROQ_API_KEY" in error


def test_empty_audio_is_rejected_before_any_network_call() -> None:
    ok, _, error = asyncio.run(
        WhisperTranscriber(_settings(groq_api_key="gk")).transcribe(b"")
    )
    assert ok is False and error == "Nothing was recorded."


def test_a_successful_transcription_returns_stripped_text(patched) -> None:
    patched(_Resp(200, {"text": "  book the interview for Tuesday  "}))
    ok, text, error = _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert ok is True and error == ""
    assert text == "book the interview for Tuesday"


def test_silence_is_reported_as_no_speech_not_as_success(patched) -> None:
    # An empty string quietly "succeeding" is how a mic button ends up doing
    # nothing at all with no explanation.
    patched(_Resp(200, {"text": "   "}))
    ok, text, error = _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert ok is False and text == ""
    assert "No speech" in error


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "key was rejected"),
        (429, "rate-limited"),
        (500, "HTTP 500"),
    ],
)
def test_vendor_errors_come_back_as_readable_reasons(patched, status, expected) -> None:
    patched(_Resp(status, None, "boom"))
    ok, _, error = _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert ok is False and expected in error


def test_a_network_failure_never_escapes_as_an_exception(patched) -> None:
    patched(httpx.ConnectError("dns"))
    ok, _, error = _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert ok is False and "Could not reach" in error


def test_an_unparseable_body_is_reported_rather_than_crashing(patched) -> None:
    patched(_Resp(200, None, "<html>"))
    ok, _, error = _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert ok is False and "unreadable" in error


# --- Request shape ---


def test_the_request_targets_the_resolved_provider_with_its_own_model(patched) -> None:
    sink: dict = {}
    patched(_Resp(200, {"text": "hi"}), sink)
    _run(WhisperTranscriber(_settings(stt_provider="groq", groq_api_key="gk")))

    assert sink["url"].startswith("https://api.groq.com/")
    assert sink["headers"]["Authorization"] == "Bearer gk"
    assert sink["data"]["model"] == "whisper-large-v3-turbo"


def test_an_omitted_language_lets_whisper_detect_it(patched) -> None:
    sink: dict = {}
    patched(_Resp(200, {"text": "hi"}), sink)
    _run(WhisperTranscriber(_settings(groq_api_key="gk")))
    assert "language" not in sink["data"]


def test_a_language_hint_is_forwarded_when_given(patched) -> None:
    sink: dict = {}
    patched(_Resp(200, {"text": "hi"}), sink)
    asyncio.run(
        WhisperTranscriber(_settings(groq_api_key="gk")).transcribe(b"x" * 900, language="hi")
    )
    assert sink["data"]["language"] == "hi"


def test_a_long_vocabulary_prompt_is_truncated_not_sent_whole(patched) -> None:
    # The prompt field is a bias hint, not a payload; an unbounded one would
    # cost tokens on every dictation for no extra accuracy.
    sink: dict = {}
    patched(_Resp(200, {"text": "hi"}), sink)
    asyncio.run(
        WhisperTranscriber(_settings(groq_api_key="gk")).transcribe(
            b"x" * 900, prompt="word " * 500
        )
    )
    assert len(sink["data"]["prompt"]) <= 800
