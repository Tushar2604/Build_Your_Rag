"""Guard: the voice cloner must degrade gracefully with no API key.

This is the state every user hits before configuring ElevenLabs, so it has to be
the well-behaved path: never raise, never make a network call, and always return
a message that says what to do. A cloner that threw here would 500 the Clone
Voice page for anyone who hasn't signed up with a vendor yet.
"""

from __future__ import annotations

import asyncio

import pytest
from src.config.settings import Settings
from src.infrastructure.voice.elevenlabs import PROVIDER_NAME, ElevenLabsVoiceCloner


def _cloner(api_key: str = "") -> ElevenLabsVoiceCloner:
    return ElevenLabsVoiceCloner(
        Settings(elevenlabs_api_key=api_key, jwt_secret="x" * 40)
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a disabled cloner tries to open a connection."""

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("a disabled cloner must not make network calls")

    monkeypatch.setattr("httpx.AsyncClient.__init__", explode)


def test_reports_itself_disabled_without_a_key() -> None:
    assert _cloner().enabled is False


def test_reports_enabled_once_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _cloner("sk-test").enabled is True


def test_provider_name_is_stable() -> None:
    # Persisted onto every VoiceProfile, so it can't drift silently.
    assert _cloner().provider == PROVIDER_NAME == "elevenlabs"


def test_clone_returns_a_actionable_message_instead_of_raising() -> None:
    ok, voice_id, error = asyncio.run(
        _cloner().clone(name="Test", audio=b"\x00" * 1000, content_type="audio/webm")
    )
    assert ok is False
    assert voice_id == ""
    assert "ELEVENLABS_API_KEY" in error


def test_synthesize_returns_an_actionable_message_instead_of_raising() -> None:
    ok, audio, error = asyncio.run(_cloner().synthesize("vx_1", "hello"))
    assert ok is False
    assert audio == b""
    assert "ELEVENLABS_API_KEY" in error


def test_synthesize_rejects_an_unready_voice_when_enabled() -> None:
    # An empty provider id means the clone never completed; catching it here
    # avoids a pointless (and billable) round trip.
    ok, _, error = asyncio.run(_cloner("sk-test").synthesize("", "hello"))
    assert ok is False
    assert "isn't ready" in error


def test_delete_is_a_silent_no_op_when_disabled() -> None:
    # Deleting a local profile must never be blocked by vendor state.
    asyncio.run(_cloner().delete("vx_1"))


def test_delete_is_a_silent_no_op_for_a_blank_voice_id() -> None:
    asyncio.run(_cloner("sk-test").delete(""))
