"""Twilio webhook signature validation, cross-checked against the real
`twilio` SDK's `RequestValidator.compute_signature()` for this exact
url/params/token triple (verified once interactively; the SDK itself is not
a dependency of this project) so the dependency-free reimplementation isn't
only self-consistent but matches Twilio's actual algorithm."""

from __future__ import annotations

from src.infrastructure.messaging.twilio_signature import (
    compute_twilio_signature,
    verify_twilio_signature,
)

_AUTH_TOKEN = "12345"
_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
_PARAMS = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675309",
    "Digits": "1234",
    "From": "+14158675309",
    "To": "+18005551212",
}
_EXPECTED_SIGNATURE = "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_compute_matches_twilio_published_example() -> None:
    assert compute_twilio_signature(_URL, _PARAMS, _AUTH_TOKEN) == _EXPECTED_SIGNATURE


def test_verify_accepts_correct_signature() -> None:
    assert verify_twilio_signature(_URL, _PARAMS, _EXPECTED_SIGNATURE, _AUTH_TOKEN) is True


def test_verify_rejects_wrong_signature() -> None:
    assert verify_twilio_signature(_URL, _PARAMS, "not-the-right-signature", _AUTH_TOKEN) is False


def test_verify_rejects_wrong_auth_token() -> None:
    assert verify_twilio_signature(_URL, _PARAMS, _EXPECTED_SIGNATURE, "wrong-token") is False


def test_verify_rejects_tampered_params() -> None:
    tampered = {**_PARAMS, "Digits": "9999"}
    assert verify_twilio_signature(_URL, tampered, _EXPECTED_SIGNATURE, _AUTH_TOKEN) is False


def test_verify_rejects_empty_signature() -> None:
    assert verify_twilio_signature(_URL, _PARAMS, "", _AUTH_TOKEN) is False
