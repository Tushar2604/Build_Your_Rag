"""One OAuth 2.0 authorization-code client, configured per provider.

Every integration that connects by consent — Google Calendar, Google Sheets,
Cal.com — runs the identical three steps: send the user to a consent screen,
swap the returned code for tokens, then refresh those tokens before they expire.
The only differences are two URLs, a scope string, and where the account's
display name lives in the identity response. So this is one client parameterised
by a spec, not a class per vendor.

The point of the whole thing, from the user's side: they click Connect, approve
in their own account, and land back on the page connected. They are never asked
to find an API key, and the platform never sees their password.

Providers whose credentials are unset report `enabled = False` — the card then
renders as "not configured" rather than sending someone to a consent screen that
would reject them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config.settings import Settings

# Google issues one refresh token per (client, user, scope-set) and only on the
# *first* consent unless re-prompted, so both Google providers ask explicitly.
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"


@dataclass(frozen=True)
class OAuthProviderSpec:
    """Everything that differs between one OAuth vendor and the next."""

    id: str
    name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    # Endpoint returning who authorised, and the JSON key holding a label for
    # them. Blank = the provider offers none, and the card shows "Connected".
    identity_url: str = ""
    identity_field: str = "email"
    # Extra params on the consent URL. Google needs these to return a refresh
    # token at all; other vendors generally need none.
    authorize_extra: dict[str, str] = field(default_factory=dict)


PROVIDER_SPECS: dict[str, OAuthProviderSpec] = {
    # Sign in with Google. The odd one out: it proves who someone is and then
    # throws the tokens away, where every other provider here stores them to act
    # on the user's behalf later. It reuses this machinery because the consent
    # dance is identical — only the scopes and what happens afterwards differ.
    #
    # No `access_type: offline` and no `prompt: consent`: a refresh token would
    # be a long-lived credential we have no use for, and re-prompting someone
    # who is already signed in to Google turns one click into three.
    "google_login": OAuthProviderSpec(
        id="google_login",
        name="Google",
        authorize_url=_GOOGLE_AUTH,
        token_url=_GOOGLE_TOKEN,
        scopes=("openid", "email", "profile"),
        identity_url=_GOOGLE_USERINFO,
    ),
    "google_calendar": OAuthProviderSpec(
        id="google_calendar",
        name="Google Calendar",
        authorize_url=_GOOGLE_AUTH,
        token_url=_GOOGLE_TOKEN,
        scopes=(
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/userinfo.email",
        ),
        identity_url=_GOOGLE_USERINFO,
        authorize_extra={"access_type": "offline", "prompt": "consent"},
    ),
    "google_sheets": OAuthProviderSpec(
        id="google_sheets",
        name="Google Sheets",
        authorize_url=_GOOGLE_AUTH,
        token_url=_GOOGLE_TOKEN,
        scopes=(
            "https://www.googleapis.com/auth/spreadsheets",
            # drive.file, not drive: this grants access only to files the app
            # itself creates or the user explicitly opens with it, rather than
            # the user's entire Drive.
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/userinfo.email",
        ),
        identity_url=_GOOGLE_USERINFO,
        authorize_extra={"access_type": "offline", "prompt": "consent"},
    ),
    "cal_com": OAuthProviderSpec(
        id="cal_com",
        name="Cal.com",
        # Cal.com exposes OAuth through its Platform product: you register a
        # client and are given these endpoints for your own instance. They are
        # therefore configurable rather than hard-coded — see CAL_COM_* in .env.
        authorize_url="",
        token_url="",
        scopes=(),
        identity_url="",
    ),
}


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str
    account_label: str = ""


class OAuthClient:
    """The authorization-code dance for one provider."""

    def __init__(self, spec: OAuthProviderSpec, settings: Settings) -> None:
        self._spec = spec
        self._settings = settings
        creds = settings.oauth_credentials(spec.id)
        self._client_id = creds.get("client_id", "")
        self._client_secret = creds.get("client_secret", "")
        # A provider may override the endpoints (Cal.com always does, since its
        # OAuth lives on the customer's own Platform instance).
        self._authorize_url = creds.get("authorize_url") or spec.authorize_url
        self._token_url = creds.get("token_url") or spec.token_url

    @property
    def spec(self) -> OAuthProviderSpec:
        return self._spec

    @property
    def enabled(self) -> bool:
        return bool(
            self._client_id and self._client_secret and self._authorize_url and self._token_url
        )

    @property
    def redirect_uri(self) -> str:
        return self._settings.oauth_redirect_uri(self._spec.id)

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            **self._spec.authorize_extra,
        }
        if self._spec.scopes:
            params["scope"] = " ".join(self._spec.scopes)
        return f"{self._authorize_url}?{urlencode(params)}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        tokens = OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=datetime.now(UTC) + timedelta(seconds=data.get("expires_in", 3600)),
            scope=data.get("scope", " ".join(self._spec.scopes)),
        )
        tokens.account_label = await self._fetch_identity(tokens.access_token)
        return tokens

    async def fetch_profile(self, access_token: str) -> dict:
        """The full identity payload, for sign-in.

        Unlike `_fetch_identity` this one is allowed to fail loudly: signing
        somebody in *is* the identity lookup, so a failure here must abort rather
        than produce a session for an unknown person.
        """
        if not self._spec.identity_url:
            return {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self._spec.identity_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            payload = resp.json()
        return payload if isinstance(payload, dict) else {}

    async def _fetch_identity(self, access_token: str) -> str:
        """Who authorised, for the "Connected as …" line.

        Failures are swallowed: the connection itself is already established at
        this point, and refusing it because a cosmetic label lookup failed would
        make the user redo consent for nothing.
        """
        if not self._spec.identity_url:
            return ""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    self._spec.identity_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                return str(resp.json().get(self._spec.identity_field, ""))
        except Exception:  # noqa: BLE001
            return ""

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def refresh(self, refresh_token: str) -> tuple[str, datetime]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return (
            data["access_token"],
            datetime.now(UTC) + timedelta(seconds=data.get("expires_in", 3600)),
        )


class OAuthBroker:
    """Registry of configured OAuth clients, one per provider id."""

    def __init__(self, settings: Settings) -> None:
        self._clients = {
            pid: OAuthClient(spec, settings) for pid, spec in PROVIDER_SPECS.items()
        }

    def get(self, provider_id: str) -> OAuthClient | None:
        return self._clients.get(provider_id)

    def enabled_ids(self) -> set[str]:
        return {pid for pid, client in self._clients.items() if client.enabled}
