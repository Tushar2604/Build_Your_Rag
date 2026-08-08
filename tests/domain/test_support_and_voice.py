"""Unit tests for issue reports and cloned-voice profiles."""

from __future__ import annotations

import pytest
from src.domain.shared.identifiers import TenantId, new_id
from src.domain.support.entities import (
    ALL_PRIORITIES,
    ALL_REPORT_TYPES,
    PRIORITY_LABELS,
    REPORT_TYPE_LABELS,
    IssueReport,
)
from src.domain.voice.entities import VoiceProfile

# --- Issue reports ---


def _report(**kwargs) -> IssueReport:
    base = {
        "tenant_id": TenantId(new_id()),
        "name": "Tushar",
        "email": "t@example.com",
        "report_type": "bug",
        "subject": "Broadcast stops early",
        "description": "The campaign stops after twenty contacts and never resumes.",
    }
    return IssueReport(**{**base, **kwargs})


def test_a_complete_report_validates() -> None:
    assert _report().validation_error() is None


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"name": "  "}, "name is required"),
        ({"email": "not-an-email"}, "valid email"),
        ({"subject": ""}, "short summary"),
        ({"description": "broken"}, "at least 20 characters"),
        ({"phone": "hello there"}, "phone number"),
    ],
)
def test_validation_rejects_incomplete_reports(kwargs: dict, fragment: str) -> None:
    error = _report(**kwargs).validation_error()
    assert error is not None and fragment in error


def test_phone_is_optional() -> None:
    assert _report(phone="").validation_error() is None


@pytest.mark.parametrize("phone", ["+971 55 375 2665", "(415) 523-8886", "+917502163963"])
def test_common_phone_formats_are_accepted(phone: str) -> None:
    # A report must never be rejected over phone formatting.
    assert _report(phone=phone).validation_error() is None


def test_normalized_trims_and_clips() -> None:
    report = _report(name="  Tushar  ", description="x" * 9000).normalized()
    assert report.name == "Tushar"
    assert len(report.description) == 5000


def test_email_subject_leads_with_priority_and_type() -> None:
    # So an inbox rule can route on it without parsing the body.
    subject = _report(priority="critical", report_type="bug").email_subject()
    assert subject.startswith("[CRITICAL]")
    assert "Broadcast stops early" in subject


def test_every_type_and_priority_has_a_label() -> None:
    assert set(REPORT_TYPE_LABELS) == set(ALL_REPORT_TYPES)
    assert set(PRIORITY_LABELS) == set(ALL_PRIORITIES)


# --- Voice profiles ---


def _voice(**kwargs) -> VoiceProfile:
    base = {
        "tenant_id": TenantId(new_id()),
        "name": "My Professional Voice",
        "duration_seconds": 35.0,
        "sample_content_type": "audio/webm",
    }
    return VoiceProfile(**{**base, **kwargs})


def _err(profile: VoiceProfile) -> str | None:
    return profile.validation_error(min_seconds=20, max_seconds=300)


def test_a_valid_sample_passes() -> None:
    assert _err(_voice()) is None


def test_short_sample_is_rejected_with_its_actual_length() -> None:
    error = _err(_voice(duration_seconds=12.0))
    assert error is not None and "at least 20 seconds" in error and "12s" in error


def test_overlong_sample_is_rejected() -> None:
    error = _err(_voice(duration_seconds=600.0))
    assert error is not None and "300 seconds or shorter" in error


def test_unsupported_audio_format_is_rejected() -> None:
    error = _err(_voice(sample_content_type="video/mp4"))
    assert error is not None and "video/mp4" in error


@pytest.mark.parametrize(
    "content_type", ["audio/webm", "audio/mpeg", "audio/wav", "audio/m4a", "audio/ogg"]
)
def test_browser_and_file_picker_formats_are_accepted(content_type: str) -> None:
    assert _err(_voice(sample_content_type=content_type)) is None


def test_unknown_language_is_rejected() -> None:
    error = _err(_voice(language="klingon"))
    assert error is not None and "klingon" in error


def test_blank_name_is_rejected() -> None:
    assert "voice name is required" in (_err(_voice(name="   ")) or "")


def test_lifecycle_from_pending_to_ready() -> None:
    voice = _voice()
    assert voice.status == "pending" and not voice.is_usable()
    voice.mark_ready("elevenlabs", "vx_123")
    assert voice.is_usable()
    assert voice.provider == "elevenlabs" and voice.provider_voice_id == "vx_123"


def test_failure_records_the_reason_and_stays_unusable() -> None:
    voice = _voice()
    voice.mark_failed("sample too short" * 500)
    assert voice.status == "failed"
    assert not voice.is_usable()
    assert len(voice.error) == 1000


def test_ready_without_a_provider_id_is_not_usable() -> None:
    # Guards against a provider returning 200 with an empty voice id.
    voice = _voice()
    voice.mark_ready("elevenlabs", "")
    assert not voice.is_usable()


def test_retry_after_failure_clears_the_error() -> None:
    voice = _voice()
    voice.mark_failed("provider down")
    voice.mark_ready("elevenlabs", "vx_9")
    assert voice.error == "" and voice.is_usable()
