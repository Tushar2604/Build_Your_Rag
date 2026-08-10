"""The OAuth connect flow's security-relevant parts.

`state` is the only thing tying a consent callback back to the tenant who
started it: the popup may not share a session, and the vendor will happily
deliver a code to anyone holding the redirect URL. So the interesting tests here
are the rejections.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from src.config.settings import get_settings
from src.infrastructure.oauth.providers import PROVIDER_SPECS, OAuthBroker
from src.interfaces.api.routers.oauth import (
    _STATE_AUDIENCE,
    _popup_result_page,
    _sign_state,
    _verify_state,
)


def test_a_signed_state_round_trips() -> None:
    tenant_id = uuid.uuid4()
    state = _sign_state(str(tenant_id), "google_calendar")
    assert _verify_state(state, "google_calendar") == tenant_id


def test_a_state_for_one_provider_cannot_be_redeemed_as_another() -> None:
    # Otherwise a consent obtained for the narrow calendar scope could be
    # redeemed as Sheets, whose scopes are wider.
    state = _sign_state(str(uuid.uuid4()), "google_calendar")
    with pytest.raises(HTTPException) as exc:
        _verify_state(state, "google_sheets")
    assert exc.value.status_code == 400


def test_an_expired_state_is_rejected() -> None:
    state = jwt.encode(
        {
            "tenant_id": str(uuid.uuid4()),
            "provider": "google_calendar",
            "aud": _STATE_AUDIENCE,
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException):
        _verify_state(state, "google_calendar")


def test_a_state_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "tenant_id": str(uuid.uuid4()),
            "provider": "google_calendar",
            "aud": _STATE_AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "not-the-servers-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException):
        _verify_state(forged, "google_calendar")


def test_an_access_token_cannot_be_presented_as_oauth_state() -> None:
    """Both are signed with the same secret, so the audience claim is what keeps
    them from being interchangeable."""
    access_like = jwt.encode(
        {
            "tenant_id": str(uuid.uuid4()),
            "provider": "google_calendar",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException):
        _verify_state(access_like, "google_calendar")


class TestPopupPage:
    def test_the_result_is_posted_only_to_our_own_origin(self) -> None:
        # A wildcard target would let any page that opened this popup read the
        # outcome of someone else's consent.
        body = _popup_result_page("google_calendar", True, "Connected.").body.decode()
        assert get_settings().public_frontend_base in body
        assert '"*"' not in body

    def test_a_failure_message_is_html_escaped(self) -> None:
        # Vendor error text ends up in this page; unescaped it would be markup.
        body = _popup_result_page(
            "cal_com", False, "<img src=x onerror=alert(1)>"
        ).body.decode()
        assert "<img src=x" not in body
        assert "&lt;img" in body


class TestProviderConfiguration:
    def test_every_spec_builds_a_client(self) -> None:
        broker = OAuthBroker(get_settings())
        for provider_id in PROVIDER_SPECS:
            assert broker.get(provider_id) is not None

    def test_a_provider_without_credentials_is_not_enabled(self) -> None:
        # Its card then reads "not configured" instead of sending someone to a
        # consent screen that would reject them.
        broker = OAuthBroker(get_settings())
        client = broker.get("cal_com")
        assert client is not None
        assert client.enabled is False

    def test_both_google_providers_share_one_oauth_app(self) -> None:
        settings = get_settings()
        calendar = settings.oauth_credentials("google_calendar")
        sheets = settings.oauth_credentials("google_sheets")
        assert calendar["client_id"] == sheets["client_id"]

    def test_each_provider_gets_its_own_redirect_uri(self) -> None:
        # They are registered separately in the vendor console, so a shared path
        # would make one of them unregisterable.
        settings = get_settings()
        uris = {settings.oauth_redirect_uri(p) for p in PROVIDER_SPECS}
        assert len(uris) == len(PROVIDER_SPECS)

    def test_sheets_asks_only_for_file_scoped_drive_access(self) -> None:
        # `drive.file` grants access to files this app creates or the user opens
        # with it — not the user's entire Drive.
        scopes = PROVIDER_SPECS["google_sheets"].scopes
        assert "https://www.googleapis.com/auth/drive.file" in scopes
        assert "https://www.googleapis.com/auth/drive" not in scopes

    def test_google_asks_for_offline_access(self) -> None:
        # Without it Google issues no refresh token and the connection silently
        # dies an hour later.
        for provider_id in ("google_calendar", "google_sheets"):
            extra = PROVIDER_SPECS[provider_id].authorize_extra
            assert extra.get("access_type") == "offline"
