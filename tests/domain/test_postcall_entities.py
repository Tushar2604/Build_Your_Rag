"""Unit tests for post-call configuration: trigger matching and validation."""

from __future__ import annotations

import pytest
from src.domain.postcall.entities import PostCallConfig, PostCallDelivery
from src.domain.shared.identifiers import ChatbotId, TenantId, new_id


def _config(**kwargs) -> PostCallConfig:
    base = {
        "tenant_id": TenantId(new_id()),
        "chatbot_id": ChatbotId(new_id()),
        "delivery_method": "webhook",
        "webhook_url": "https://ats.example.com/hook",
    }
    return PostCallConfig(**{**base, **kwargs})


def test_triggers_only_on_selected_statuses() -> None:
    config = _config(trigger_statuses=["completed", "no_answer"])
    assert config.triggers_on("completed")
    assert config.triggers_on("no_answer")
    assert not config.triggers_on("failed")


def test_disabled_config_never_triggers() -> None:
    config = _config(trigger_statuses=["completed"], enabled=False)
    assert not config.triggers_on("completed")


def test_destination_follows_the_delivery_method() -> None:
    webhook = _config()
    assert webhook.destination() == "https://ats.example.com/hook"
    email = _config(delivery_method="email", webhook_url="", email_to="hr@example.com")
    assert email.destination() == "hr@example.com"


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"webhook_url": ""}, "webhook URL is required"),
        ({"webhook_url": "ats.example.com/hook"}, "must start with http"),
        ({"trigger_statuses": []}, "at least one call status"),
        (
            {
                "include_summary": False,
                "include_transcript": False,
                "include_sentiment": False,
                "include_extracted": False,
            },
            "at least one item to include",
        ),
    ],
)
def test_validation_rejects_unusable_configs(kwargs: dict, fragment: str) -> None:
    error = _config(**kwargs).validation_error()
    assert error is not None and fragment in error


def test_validation_rejects_a_malformed_email() -> None:
    config = _config(delivery_method="email", webhook_url="", email_to="not-an-address")
    error = config.validation_error()
    assert error is not None and "valid destination email" in error


def test_a_usable_config_validates() -> None:
    assert _config().validation_error() is None


def test_unknown_trigger_status_is_named_in_the_error() -> None:
    error = _config(trigger_statuses=["completed", "abducted"]).validation_error()
    assert error is not None and "abducted" in error


def test_delivery_marks_and_clips_long_errors() -> None:
    delivery = PostCallDelivery(
        tenant_id=TenantId(new_id()),
        chatbot_id=ChatbotId(new_id()),
        config_id=new_id(),
        session_id=new_id(),
        call_status="completed",
    )
    delivery.mark_failed("x" * 5000)
    assert delivery.status == "failed"
    assert len(delivery.error) == 1000

    delivery.mark_delivered()
    assert delivery.status == "delivered"
    assert delivery.error == ""
