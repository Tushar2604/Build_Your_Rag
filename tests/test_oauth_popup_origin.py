"""Where an OAuth popup is allowed to deliver its result.

This is a security boundary, not a convenience: the callback posts an access
token (sign-in) or a connection result to whichever origin is named, so anything
that gets past these checks can receive a session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from src.config.settings import Settings
from src.interfaces.api.oauth_popup import (
    STATE_AUDIENCE,
    popup_result_page,
    resolve_origin,
    sign_state,
    state_origin,
    verify_state,
)

_ACTIVE: dict[str, Settings] = {}


def _use(**kwargs) -> Settings:
    """Run the rest of this test against a specific configuration."""
    settings = Settings(**kwargs)
    _ACTIVE["settings"] = settings
    return settings


@pytest.fixture(autouse=True)
def _patch_get_settings(monkeypatch):
    """Swap the cached settings singleton for whatever `_use` installed.

    `get_settings` is an `lru_cache`, so clearing it would just re-read the
    developer's real `.env` — substituting the accessor is what keeps these
    tests independent of the machine they run on.
    """
    monkeypatch.setattr(
        "src.interfaces.api.oauth_popup.get_settings",
        lambda: _ACTIVE.get("settings") or Settings(),
    )
    yield
    _ACTIVE.clear()


class TestProductionOrigins:
    def test_a_configured_origin_is_accepted(self) -> None:
        _use(
            app_env="production",
            jwt_secret="a" * 48,
            app_base_url="https://app.example.com",
        )
        assert resolve_origin("https://app.example.com") == "https://app.example.com"

    def test_a_separate_frontend_origin_is_accepted(self) -> None:
        _use(
            app_env="production",
            jwt_secret="a" * 48,
            app_base_url="https://api.example.com",
            frontend_base_url="https://app.example.com",
        )
        assert resolve_origin("https://app.example.com") == "https://app.example.com"

    def test_an_unknown_origin_falls_back_rather_than_being_honoured(self) -> None:
        # The attack this prevents: a page on evil.example asks for a sign-in
        # popup and receives the resulting session by postMessage.
        _use(
            app_env="production",
            jwt_secret="a" * 48,
            app_base_url="https://app.example.com",
        )
        assert resolve_origin("https://evil.example") == "https://app.example.com"

    def test_localhost_is_not_trusted_in_production(self) -> None:
        _use(
            app_env="production",
            jwt_secret="a" * 48,
            app_base_url="https://app.example.com",
        )
        assert resolve_origin("http://localhost:5173") == "https://app.example.com"


class TestDevelopmentOrigins:
    def test_the_vite_dev_server_is_trusted(self) -> None:
        # The SPA runs on :5173 while the API runs on :8000; requiring an env var
        # to be kept in sync between them silently breaks the handshake.
        _use(app_base_url="http://localhost:8000")
        assert resolve_origin("http://localhost:5173") == "http://localhost:5173"

    def test_loopback_by_ip_is_trusted(self) -> None:
        _use(app_base_url="http://localhost:8000")
        assert resolve_origin("http://127.0.0.1:3000") == "http://127.0.0.1:3000"

    def test_a_remote_origin_is_still_refused_in_development(self) -> None:
        _use(app_base_url="http://localhost:8000")
        assert resolve_origin("https://evil.example") == "http://localhost:8000"

    def test_no_origin_header_falls_back(self) -> None:
        _use(app_base_url="http://localhost:8000")
        assert resolve_origin(None) == "http://localhost:8000"


class TestState:
    def test_a_round_trip_preserves_the_claims(self) -> None:
        _use(jwt_secret="a" * 48, app_base_url="http://localhost:8000")
        token = sign_state("google_calendar", "http://localhost:5173", tenant_id="t-1")

        payload = verify_state(token, "google_calendar")

        assert payload["tenant_id"] == "t-1"
        assert state_origin(payload) == "http://localhost:5173"

    def test_a_consent_for_one_provider_cannot_be_redeemed_as_another(self) -> None:
        # Otherwise a calendar consent could be presented to the sign-in
        # callback, or a narrow scope swapped for a wider one.
        _use(jwt_secret="a" * 48)
        token = sign_state("google_calendar", "http://localhost:8000")

        with pytest.raises(HTTPException) as exc:
            verify_state(token, "google_login")
        assert exc.value.status_code == 400

    def test_a_token_signed_with_another_secret_is_rejected(self) -> None:
        _use(jwt_secret="a" * 48)
        forged = jwt.encode(
            {"provider": "google_login", "origin": "https://evil.example", "aud": STATE_AUDIENCE},
            "not-the-secret",
            algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            verify_state(forged, "google_login")

    def test_an_expired_state_is_rejected(self) -> None:
        _use(jwt_secret="a" * 48)
        stale = jwt.encode(
            {
                "provider": "google_login",
                "origin": "http://localhost:8000",
                "aud": STATE_AUDIENCE,
                "exp": datetime.now(UTC) - timedelta(minutes=1),
            },
            "a" * 48,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            verify_state(stale, "google_login")

    def test_an_access_token_cannot_be_presented_as_oauth_state(self) -> None:
        """Both are signed with the same secret, so the audience claim is the
        only thing keeping them from being interchangeable."""
        _use(jwt_secret="a" * 48)
        access_like = jwt.encode(
            {
                "provider": "google_login",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "a" * 48,
            algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            verify_state(access_like, "google_login")

    def test_an_origin_smuggled_into_a_valid_state_is_still_checked(self) -> None:
        """Belt and braces.

        The state is signed, so this should be unreachable — but the cost of
        being wrong is posting a session to somebody else's page.
        """
        _use(app_env="production", jwt_secret="a" * 48, app_base_url="https://app.example.com")
        token = sign_state("google_login", "https://evil.example")
        payload = verify_state(token, "google_login")

        assert state_origin(payload) == "https://app.example.com"


class TestResultPage:
    def test_the_target_origin_is_explicit_never_a_wildcard(self) -> None:
        _use(app_base_url="http://localhost:8000")
        body = popup_result_page(
            ok=True, message="Signed in.", origin="http://localhost:5173"
        ).body.decode()

        assert '"http://localhost:5173"' in body
        assert '"*"' not in body

    def test_the_message_is_escaped(self) -> None:
        # Vendor and domain errors flow into this page verbatim.
        _use(app_base_url="http://localhost:8000")
        body = popup_result_page(
            ok=False, message="<img src=x onerror=alert(1)>", origin="http://localhost:8000"
        ).body.decode()

        assert "<img src=x" not in body
        assert "&lt;img" in body
