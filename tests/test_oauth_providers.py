"""How each OAuth provider is configured.

State signing and the popup origin check live in `test_oauth_popup_origin.py`;
this file is about the provider registry — which vendors exist, what they ask
for, and what happens when one has no credentials.
"""

from __future__ import annotations

from src.config.settings import get_settings
from src.infrastructure.oauth.providers import PROVIDER_SPECS, OAuthBroker


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
