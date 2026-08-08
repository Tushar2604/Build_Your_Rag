"""Cloned voices — a custom AI voice built from a tenant's own audio sample.

The sample lives in object storage; `provider_voice_id` is the handle the TTS
vendor gives back and is what synthesis actually uses. A profile is useful the
moment it is `ready`; before that it is a stored recording and nothing more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, get_args

from src.domain.shared.identifiers import TenantId, new_id

Gender = Literal["female", "male", "neutral"]
ALL_GENDERS: tuple[Gender, ...] = get_args(Gender)

# pending -> uploaded, not yet sent to the provider
# ready   -> the provider returned a usable voice id
# failed  -> the provider rejected it; `error` says why
VoiceStatus = Literal["pending", "ready", "failed"]

# The languages the UI offers. Kept small and explicit rather than an open text
# field, because the provider validates this and a typo fails the whole clone.
SUPPORTED_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("pt", "Portuguese"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
)
SUPPORTED_LANGUAGE_CODES: frozenset[str] = frozenset(code for code, _ in SUPPORTED_LANGUAGES)

# Audio containers a browser MediaRecorder or a file picker realistically
# produces. Anything else is rejected before it reaches storage.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/flac",
    }
)

MAX_NAME = 80
MAX_DESCRIPTION = 500


@dataclass
class VoiceProfile:
    tenant_id: TenantId
    name: str
    id: uuid.UUID = field(default_factory=new_id)
    gender: Gender = "female"
    language: str = "en"
    description: str = ""
    # Where the source recording lives, so a failed clone can be retried without
    # asking the user to record again.
    sample_storage_key: str = ""
    sample_content_type: str = ""
    sample_bytes: int = 0
    duration_seconds: float = 0.0
    provider: str = ""
    provider_voice_id: str = ""
    status: VoiceStatus = "pending"
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def mark_ready(self, provider: str, provider_voice_id: str) -> None:
        self.provider = provider
        self.provider_voice_id = provider_voice_id
        self.status = "ready"
        self.error = ""
        self._touch()

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error[:1000]
        self._touch()

    def is_usable(self) -> bool:
        return self.status == "ready" and bool(self.provider_voice_id)

    def validation_error(self, *, min_seconds: int, max_seconds: int) -> str | None:
        if not self.name.strip():
            return "A voice name is required."
        if self.gender not in ALL_GENDERS:
            return "Choose a gender for this voice."
        if self.language not in SUPPORTED_LANGUAGE_CODES:
            return f"'{self.language}' isn't a supported language."
        if self.sample_content_type and self.sample_content_type not in ALLOWED_CONTENT_TYPES:
            return f"'{self.sample_content_type}' isn't a supported audio format."
        if self.duration_seconds < min_seconds:
            # The floor is the provider's, not ours: a shorter sample produces a
            # clone that doesn't sound like anyone.
            return (
                f"The sample must be at least {min_seconds} seconds "
                f"(this one is {self.duration_seconds:.0f}s)."
            )
        if self.duration_seconds > max_seconds:
            return f"The sample must be {max_seconds} seconds or shorter."
        return None

    def normalized(self) -> VoiceProfile:
        self.name = self.name.strip()[:MAX_NAME]
        self.description = self.description.strip()[:MAX_DESCRIPTION]
        return self
