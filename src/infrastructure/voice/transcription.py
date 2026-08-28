"""Speech-to-text for the dictation button.

Follows the same opt-in shape as the other external adapters: with no usable
API key it reports `enabled is False` and every call returns a readable "not
configured" outcome rather than raising. The mic button then falls back to the
browser's own recogniser, or hides itself if that is missing too.

One adapter serves both vendors because Groq deliberately mirrors OpenAI's
`/audio/transcriptions` contract — same multipart shape, same response body —
so the only differences are the base URL, the key, and the model id. That is
also why no vendor SDK is imported here: two SDKs for one identical multipart
POST would be more code, not less.

Never raises. A dictation that fails must leave the user's typed text alone and
say why, not 500 the request or wipe the field they were dictating into.
"""

from __future__ import annotations

import httpx
import structlog

from src.config.settings import Settings
from src.infrastructure.http_client import get_client

log = structlog.get_logger(__name__)

# Generous relative to a spoken phrase, but a cold Whisper worker plus a 2MB
# upload on hotel wifi is genuinely slow, and a timeout here reads to the user
# as "dictation is broken".
TIMEOUT_SECONDS = 90

_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1/audio/transcriptions",
    "openai": "https://api.openai.com/v1/audio/transcriptions",
}

_NOT_CONFIGURED = (
    "Server dictation isn't configured. Add GROQ_API_KEY or OPENAI_API_KEY to "
    ".env to enable it."
)


class WhisperTranscriber:
    def __init__(self, settings: Settings) -> None:
        self._provider, self._api_key = settings.resolve_stt()
        self._model = settings.stt_model_for(self._provider) if self._provider else ""

    @property
    def enabled(self) -> bool:
        return bool(self._api_key and self._provider)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/webm",
        filename: str = "dictation.webm",
        language: str = "",
        prompt: str = "",
    ) -> tuple[bool, str, str]:
        """Transcribe one clip. Returns `(ok, text, error)`.

        `language` is an ISO-639-1 hint. Passing it when known measurably
        improves both accuracy and latency; omitting it lets Whisper detect,
        which is what a workspace dictating in more than one language wants.
        """
        if not self.enabled:
            return False, "", _NOT_CONFIGURED
        if not audio:
            return False, "", "Nothing was recorded."

        files = {"file": (filename, audio, content_type or "audio/webm")}
        data = {"model": self._model, "response_format": "json"}
        if language:
            data["language"] = language
        if prompt:
            # Biases the decoder toward domain vocabulary — product and
            # candidate names it would otherwise spell phonetically.
            data["prompt"] = prompt[:800]

        try:
            client = await get_client("stt", timeout=TIMEOUT_SECONDS)
            resp = await client.post(
                _BASE_URLS[self._provider],
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
            )
        except httpx.HTTPError as exc:
            log.warning("stt.request_failed", provider=self._provider, error=str(exc))
            return False, "", f"Could not reach the transcription service: {exc}"

        if resp.status_code == 401:
            return False, "", "The transcription API key was rejected."
        if resp.status_code == 429:
            return False, "", "Transcription is rate-limited right now. Try again in a moment."
        if resp.status_code >= 400:
            log.warning(
                "stt.rejected", provider=self._provider, status=resp.status_code,
                body=resp.text[:300],
            )
            return False, "", f"Transcription failed (HTTP {resp.status_code})."

        try:
            text = (resp.json().get("text") or "").strip()
        except ValueError:
            return False, "", "The transcription service returned an unreadable response."

        # A silent clip transcribes to an empty string rather than an error.
        # Said plainly, because "nothing happened" with no explanation is the
        # single most confusing outcome a mic button can produce.
        if not text:
            return False, "", "No speech was detected in that recording."
        return True, text, ""
