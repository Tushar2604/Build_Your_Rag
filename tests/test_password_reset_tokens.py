"""Password-reset tokens.

The reset token is stateless — no table, no cleanup job — so every security
property it has comes from its claims. Each of those is pinned here, because a
regression in any one of them is a silent account-takeover path rather than a
visible bug.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from src.config.settings import Settings
from src.infrastructure.security.tokens import JwtTokenService


def _service(**overrides) -> JwtTokenService:
    return JwtTokenService(
        Settings(jwt_secret="a-secret-long-enough-for-hs256-testing", **overrides)
    )


def test_a_reset_token_round_trips() -> None:
    svc = _service()
    token = svc.issue_password_reset(user_id="user-1", password_hash="hash-a")
    claims = svc.decode_password_reset(token)
    assert claims["sub"] == "user-1"
    assert svc.reset_matches_current(claims, "hash-a")


def test_an_access_token_is_not_accepted_as_a_reset_token() -> None:
    # Without the type check any valid session would authorise a password
    # change, which is the whole point of requiring the emailed link.
    svc = _service()
    pair = svc.issue(user_id="user-1", tenant_id="tenant-1", role="owner")
    with pytest.raises(jwt.InvalidTokenError):
        svc.decode_password_reset(pair.access_token)


def test_the_token_stops_working_once_the_password_changes() -> None:
    # This is what makes a stateless token single-use: the hash it was issued
    # against is fingerprinted in, so a completed reset invalidates the link —
    # including a copy someone else intercepted.
    svc = _service()
    token = svc.issue_password_reset(user_id="user-1", password_hash="hash-a")
    claims = svc.decode_password_reset(token)
    assert svc.reset_matches_current(claims, "hash-a")
    assert not svc.reset_matches_current(claims, "hash-b-after-reset")


def test_the_token_never_carries_the_password_hash() -> None:
    # The link travels by email and lands in logs and browser history.
    svc = _service()
    secret = "argon2-hash-that-must-not-leak"
    token = svc.issue_password_reset(user_id="user-1", password_hash=secret)
    assert secret not in token
    assert secret not in str(svc.decode_password_reset(token))


def test_an_expired_token_is_rejected() -> None:
    # Signed correctly, but issued and expired in the past — the shape of a link
    # someone opens a day after asking for it.
    secret = "a-secret-long-enough-for-hs256-testing"
    past = datetime.now(UTC) - timedelta(hours=2)
    stale = jwt.encode(
        {"sub": "user-1", "type": "password_reset", "pw": "x", "iat": past, "exp": past},
        secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        _service().decode_password_reset(stale)


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    issued_elsewhere = _service().issue_password_reset(user_id="user-1", password_hash="h")
    other = JwtTokenService(Settings(jwt_secret="a-different-secret-entirely-here"))
    with pytest.raises(jwt.InvalidSignatureError):
        other.decode_password_reset(issued_elsewhere)


def test_a_tampered_subject_is_rejected() -> None:
    # Swapping `sub` for another user id is the obvious attack; the signature is
    # what stops it.
    svc = _service()
    token = svc.issue_password_reset(user_id="user-1", password_hash="hash-a")
    # Re-signing with the wrong key is the only way to change a claim.
    forged = jwt.encode(
        {**svc.decode_password_reset(token), "sub": "user-2"},
        "not-the-real-secret",
        algorithm="HS256",
    )
    assert forged != token
    with pytest.raises(jwt.InvalidSignatureError):
        svc.decode_password_reset(forged)


def test_expiry_is_bounded_by_the_configured_ttl() -> None:
    svc = _service(password_reset_ttl_minutes=15)
    claims = svc.decode_password_reset(
        svc.issue_password_reset(user_id="u", password_hash="h")
    )
    lifetime = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)
    assert timedelta(minutes=14) < lifetime <= timedelta(minutes=15)
