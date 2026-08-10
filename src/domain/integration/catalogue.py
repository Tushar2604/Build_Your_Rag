"""The integrations catalogue — what a tenant can connect, and what each needs.

This is a static registry rather than database rows: the *set* of supported
integrations ships with the code (adding one means writing an adapter), while
the *connections* are per-tenant data. Keeping them apart means a deploy can add
an integration without a migration, and a tenant's stored credentials never
determine what the product claims to support.

Honesty rule: `wired` marks integrations that actually transact today. Anything
`wired=False` renders in the UI as "Setup required" with its Connect button
disabled — a card that pretends to connect and then silently does nothing is
worse than no card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, get_args

Category = Literal["calendar_crm", "messaging", "data_sheets", "custom_tools"]
ALL_CATEGORIES: tuple[Category, ...] = get_args(Category)

CATEGORY_LABELS: dict[Category, str] = {
    "calendar_crm": "Calendar & CRM",
    "messaging": "Messaging",
    "data_sheets": "Data & Sheets",
    "custom_tools": "Custom & Tools",
}

# When the integration acts: while a conversation is happening (the assistant can
# call it mid-conversation) or after it ends (post-call delivery).
Timing = Literal["during_call", "post_call"]

# How a tenant authenticates. `oauth` flows are owned by their own router;
# `fields` integrations collect the values named in `credential_fields`.
AuthKind = Literal["oauth", "fields"]


@dataclass(frozen=True)
class CredentialField:
    """One input on the Connect form."""

    key: str
    label: str
    placeholder: str = ""
    # Secrets are write-only: never echoed back to the browser once stored.
    secret: bool = False
    required: bool = True
    help_text: str = ""


@dataclass(frozen=True)
class IntegrationSpec:
    id: str
    name: str
    description: str
    category: Category
    timing: Timing
    auth: AuthKind = "fields"
    credential_fields: tuple[CredentialField, ...] = ()
    wired: bool = False
    # Shown on unwired cards so the UI can explain *why* it can't connect yet.
    unavailable_reason: str = ""
    # Set for oauth integrations whose flow lives in another router.
    oauth_start_path: str = ""

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS[self.category]


_WEBHOOK_URL = CredentialField(
    key="webhook_url",
    label="Incoming webhook URL",
    placeholder="https://hooks.slack.com/services/T000/B000/XXXX",
    secret=True,
    help_text="Slack → Apps → Incoming Webhooks → Add New Webhook to Workspace.",
)

_NEEDS_OAUTH_APP = (
    "Needs a vendor OAuth app and an adapter for its API. The connection is "
    "stored, but nothing is sent yet."
)

CATALOGUE: tuple[IntegrationSpec, ...] = (
    # --- Calendar & CRM (6) ---
    IntegrationSpec(
        id="google_calendar",
        name="Google Calendar",
        description=(
            "Let assistants check availability and put interviews on your calendar."
        ),
        category="calendar_crm",
        timing="during_call",
        auth="oauth",
        wired=True,
        oauth_start_path="/integrations/oauth/google_calendar/start",
    ),
    IntegrationSpec(
        id="cal_com",
        name="Cal.com",
        description="Sync your Cal.com calendar so assistants can book meetings for you.",
        category="calendar_crm",
        timing="during_call",
        auth="oauth",
        wired=True,
        oauth_start_path="/integrations/oauth/cal_com/start",
        # Cal.com only issues OAuth clients to its Platform customers, so unlike
        # Google this one cannot be configured from public docs alone — the card
        # says so rather than offering a Connect button that would 400.
        unavailable_reason=(
            "Needs a Cal.com Platform OAuth client. Set CAL_COM_CLIENT_ID, "
            "CAL_COM_CLIENT_SECRET, CAL_COM_AUTHORIZE_URL and CAL_COM_TOKEN_URL "
            "to enable it."
        ),
    ),
    IntegrationSpec(
        id="calendly",
        name="Calendly",
        description=(
            "Connect Calendly to check availability and schedule appointments."
        ),
        category="calendar_crm",
        timing="during_call",
        credential_fields=(
            CredentialField(key="api_key", label="Calendly personal access token", secret=True),
        ),
        unavailable_reason=_NEEDS_OAUTH_APP,
    ),
    IntegrationSpec(
        id="salesforce",
        name="Salesforce",
        description="Write finished conversations into a Salesforce object.",
        category="calendar_crm",
        timing="post_call",
        credential_fields=(
            CredentialField(key="instance_url", label="Instance URL",
                            placeholder="https://your-org.my.salesforce.com"),
            CredentialField(key="client_id", label="Consumer key", secret=True),
            CredentialField(key="client_secret", label="Consumer secret", secret=True),
        ),
        unavailable_reason=_NEEDS_OAUTH_APP,
    ),
    IntegrationSpec(
        id="hubspot",
        name="HubSpot",
        description="Push contacts and call summaries into your HubSpot CRM.",
        category="calendar_crm",
        timing="post_call",
        credential_fields=(
            CredentialField(key="access_token", label="Private app access token", secret=True),
        ),
        unavailable_reason=_NEEDS_OAUTH_APP,
    ),
    IntegrationSpec(
        id="zoho_crm",
        name="Zoho CRM",
        description="Create leads in Zoho CRM from completed conversations.",
        category="calendar_crm",
        timing="post_call",
        credential_fields=(
            CredentialField(key="refresh_token", label="Refresh token", secret=True),
            CredentialField(key="region", label="Data centre", placeholder="com | eu | in"),
        ),
        unavailable_reason=_NEEDS_OAUTH_APP,
    ),
    # --- Messaging (5) ---
    IntegrationSpec(
        id="slack",
        name="Slack",
        description=(
            "Post call summaries and transcripts to a Slack channel the moment a "
            "conversation ends."
        ),
        category="messaging",
        timing="post_call",
        credential_fields=(_WEBHOOK_URL,),
        wired=True,
    ),
    IntegrationSpec(
        id="whatsapp_twilio",
        name="WhatsApp (Twilio)",
        description="Deploy an assistant to WhatsApp and run outbound broadcasts.",
        category="messaging",
        timing="during_call",
        wired=True,
        # Connected per-chatbot under Channels rather than tenant-wide, so this
        # card points there instead of collecting credentials twice.
        unavailable_reason="",
    ),
    IntegrationSpec(
        id="telegram",
        name="Telegram",
        description="Answer Telegram messages with your assistant.",
        category="messaging",
        timing="during_call",
        credential_fields=(
            CredentialField(key="bot_token", label="Bot token", secret=True),
        ),
        unavailable_reason="Needs a Telegram bot adapter. The token is stored, "
        "but no messages are handled yet.",
    ),
    IntegrationSpec(
        id="microsoft_teams",
        name="Microsoft Teams",
        description="Send post-call reports into a Teams channel.",
        category="messaging",
        timing="post_call",
        credential_fields=(
            CredentialField(key="webhook_url", label="Incoming webhook URL", secret=True),
        ),
        unavailable_reason="Needs a Teams adapter for its message-card format.",
    ),
    IntegrationSpec(
        id="discord",
        name="Discord",
        description="Post conversation summaries to a Discord channel.",
        category="messaging",
        timing="post_call",
        credential_fields=(
            CredentialField(key="webhook_url", label="Webhook URL", secret=True),
        ),
        unavailable_reason="Needs a Discord adapter for its embed format.",
    ),
    # --- Data & Sheets (2) ---
    IntegrationSpec(
        id="google_sheets",
        name="Google Sheets",
        description="Append every finished conversation as a row in a spreadsheet.",
        category="data_sheets",
        timing="post_call",
        auth="oauth",
        wired=True,
        oauth_start_path="/integrations/oauth/google_sheets/start",
    ),
    IntegrationSpec(
        id="airtable",
        name="Airtable",
        description="Create an Airtable record for each conversation.",
        category="data_sheets",
        timing="post_call",
        credential_fields=(
            CredentialField(key="api_key", label="Personal access token", secret=True),
            CredentialField(key="base_id", label="Base ID", placeholder="appXXXXXXXXXXXXXX"),
            CredentialField(key="table_name", label="Table name", placeholder="Conversations"),
        ),
        unavailable_reason="Needs an Airtable adapter.",
    ),
    # --- Custom & Tools (1) ---
    IntegrationSpec(
        id="custom_api",
        name="Custom API",
        description=(
            "Send a signed JSON payload to any HTTPS endpoint you control — the "
            "escape hatch when there's no first-class integration."
        ),
        category="custom_tools",
        timing="post_call",
        credential_fields=(
            CredentialField(
                key="webhook_url",
                label="Endpoint URL",
                placeholder="https://api.yourcompany.com/hooks/conversations",
                help_text="Receives an HMAC-signed POST. Verify X-Signature against "
                "'{timestamp}.{body}' using your JWT secret.",
            ),
        ),
        wired=True,
    ),
)

_BY_ID: dict[str, IntegrationSpec] = {spec.id: spec for spec in CATALOGUE}


def get_spec(integration_id: str) -> IntegrationSpec | None:
    return _BY_ID.get(integration_id)


def category_counts() -> dict[str, int]:
    """Counts for the filter chips, including the 'all' pseudo-category."""
    counts: dict[str, int] = dict.fromkeys(ALL_CATEGORIES, 0)
    for spec in CATALOGUE:
        counts[spec.category] += 1
    return {"all": len(CATALOGUE), **counts}


@dataclass
class ConnectionResult:
    """Outcome of validating submitted credentials against a spec."""

    config: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def validate_credentials(spec: IntegrationSpec, submitted: dict[str, str]) -> ConnectionResult:
    """Check required fields are present and keep only fields the spec declares.

    Filtering to declared keys matters: it stops an arbitrary JSON blob (and
    whatever a caller decided to put in it) from being persisted under an
    integration's config.
    """
    if spec.auth == "oauth":
        return ConnectionResult(
            error=f"{spec.name} connects through its own authorization flow, not this form."
        )

    config: dict[str, str] = {}
    for cf in spec.credential_fields:
        value = (submitted.get(cf.key) or "").strip()
        if cf.required and not value:
            return ConnectionResult(error=f"{cf.label} is required.")
        if value:
            config[cf.key] = value

    url = config.get("webhook_url", "")
    if url and not url.startswith("https://"):
        # Credentials and transcripts travel in this URL's requests.
        return ConnectionResult(error="The webhook URL must start with https://.")

    return ConnectionResult(config=config)


def redact(spec: IntegrationSpec, config: dict[str, str]) -> dict[str, str]:
    """Mask secret fields for display. The browser never needs the real value
    back — it only needs to know something is stored."""
    secret_keys = {cf.key for cf in spec.credential_fields if cf.secret}
    return {
        key: ("••••••••" if key in secret_keys and value else value)
        for key, value in config.items()
    }
