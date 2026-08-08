"""Unit tests for the integrations catalogue: shape, credential validation, and
the redaction that keeps stored secrets out of API responses."""

from __future__ import annotations

import pytest
from src.domain.integration.catalogue import (
    ALL_CATEGORIES,
    CATALOGUE,
    CATEGORY_LABELS,
    category_counts,
    get_spec,
    redact,
    validate_credentials,
)
from src.domain.integration.entities import TenantIntegration
from src.domain.shared.identifiers import TenantId, new_id


def _spec(integration_id: str):
    spec = get_spec(integration_id)
    assert spec is not None
    return spec


# --- Catalogue shape ---


def test_ids_are_unique() -> None:
    ids = [s.id for s in CATALOGUE]
    assert len(ids) == len(set(ids))


def test_every_entry_has_a_known_category_with_a_label() -> None:
    for spec in CATALOGUE:
        assert spec.category in ALL_CATEGORIES
        assert spec.category_label == CATEGORY_LABELS[spec.category]


def test_counts_cover_every_entry() -> None:
    counts = category_counts()
    assert counts["all"] == len(CATALOGUE)
    assert sum(counts[c] for c in ALL_CATEGORIES) == len(CATALOGUE)


def test_unwired_entries_explain_themselves() -> None:
    # An unwired card renders with its Connect button disabled; without a reason
    # the UI would just look broken.
    for spec in CATALOGUE:
        if not spec.wired:
            assert spec.unavailable_reason, f"{spec.id} is unwired but gives no reason"


def test_wired_field_based_entries_declare_credentials() -> None:
    # Except WhatsApp, which is connected per-chatbot under Channels.
    for spec in CATALOGUE:
        if spec.wired and spec.auth == "fields" and spec.id != "whatsapp_twilio":
            assert spec.credential_fields, f"{spec.id} is wired but collects nothing"


def test_oauth_entries_point_at_their_flow() -> None:
    for spec in CATALOGUE:
        if spec.auth == "oauth":
            assert spec.oauth_start_path


def test_unknown_id_resolves_to_none() -> None:
    assert get_spec("not_a_real_integration") is None


# --- Credential validation ---


def test_accepts_a_valid_slack_webhook() -> None:
    result = validate_credentials(
        _spec("slack"), {"webhook_url": "https://hooks.slack.com/services/T/B/X"}
    )
    assert result.error is None
    assert result.config == {"webhook_url": "https://hooks.slack.com/services/T/B/X"}


def test_missing_required_field_names_the_label() -> None:
    result = validate_credentials(_spec("slack"), {})
    assert result.error is not None and "Incoming webhook URL" in result.error


def test_plaintext_webhook_is_rejected() -> None:
    # Transcripts and credentials ride in these requests.
    result = validate_credentials(
        _spec("custom_api"), {"webhook_url": "http://example.com/hook"}
    )
    assert result.error is not None and "https://" in result.error


def test_undeclared_keys_are_dropped() -> None:
    # Otherwise an arbitrary JSON blob would be persisted under the integration.
    result = validate_credentials(
        _spec("slack"),
        {"webhook_url": "https://hooks.slack.com/x", "evil": "payload", "admin": "true"},
    )
    assert result.config == {"webhook_url": "https://hooks.slack.com/x"}


def test_optional_fields_may_be_omitted() -> None:
    result = validate_credentials(_spec("custom_api"), {"webhook_url": "https://a.example/x"})
    assert result.error is None


def test_oauth_integrations_reject_the_credential_form() -> None:
    result = validate_credentials(_spec("google_calendar"), {"api_key": "x"})
    assert result.error is not None and "authorization flow" in result.error


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_required_value_is_rejected(value: str) -> None:
    assert validate_credentials(_spec("slack"), {"webhook_url": value}).error is not None


# --- Redaction ---


def test_secret_fields_are_masked() -> None:
    spec = _spec("slack")
    masked = redact(spec, {"webhook_url": "https://hooks.slack.com/services/T/B/SECRET"})
    assert masked["webhook_url"] == "••••••••"
    assert "SECRET" not in str(masked)


def test_non_secret_fields_survive_redaction() -> None:
    spec = _spec("google_sheets")
    masked = redact(spec, {"spreadsheet_id": "abc123", "worksheet": "Sheet1"})
    assert masked == {"spreadsheet_id": "abc123", "worksheet": "Sheet1"}


def test_empty_secret_is_not_masked_into_looking_set() -> None:
    # Masking "" would make an unset credential look configured.
    assert redact(_spec("slack"), {"webhook_url": ""})["webhook_url"] == ""


# --- Connection entity ---


def test_replace_config_swaps_credentials_and_touches_timestamp() -> None:
    conn = TenantIntegration(
        tenant_id=TenantId(new_id()), integration_id="slack", config={"webhook_url": "https://a"}
    )
    before = conn.updated_at
    conn.replace_config({"webhook_url": "https://b"})
    assert conn.webhook_url() == "https://b"
    assert conn.updated_at >= before


def test_webhook_url_defaults_to_empty() -> None:
    conn = TenantIntegration(tenant_id=TenantId(new_id()), integration_id="hubspot")
    assert conn.webhook_url() == ""
