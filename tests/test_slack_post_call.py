"""Unit tests for Slack post-call delivery: block rendering and config validation.

Slack is the one messaging integration wired end to end, and it's the payoff for
the Integrations page — connecting it makes "deliver post-call reports to Slack"
a real option in Post-Call settings.
"""

from __future__ import annotations

import pytest
from src.domain.postcall.entities import PostCallConfig
from src.domain.shared.identifiers import ChatbotId, TenantId, new_id
from src.infrastructure.messaging.slack import MAX_BLOCK_CHARS, post_call_blocks


def _payload(**kwargs) -> dict:
    base = {
        "event": "post_call",
        "chatbot": "HR Assistant",
        "call_status": "completed",
        "message_count": 8,
    }
    return {**base, **kwargs}


def _texts(blocks: list[dict]) -> str:
    """Flatten every block's text so a test can assert on content without
    depending on which block index it landed in."""
    out = []
    for block in blocks:
        text = block.get("text")
        if isinstance(text, dict):
            out.append(text.get("text", ""))
        for element in block.get("elements", []):
            out.append(element.get("text", ""))
    return "\n".join(out)


# --- Block rendering ---


def test_fallback_text_names_the_assistant_and_outcome() -> None:
    # This is what shows in a Slack notification preview.
    fallback, _ = post_call_blocks(_payload())
    assert "HR Assistant" in fallback and "completed" in fallback


def test_header_and_context_are_always_present() -> None:
    _, blocks = post_call_blocks(_payload())
    assert blocks[0]["type"] == "header"
    assert "8" in _texts(blocks)


def test_only_included_blocks_are_rendered() -> None:
    # A config that asked for nothing but the transcript shouldn't produce empty
    # "Summary" / "Sentiment" headings.
    _, blocks = post_call_blocks(_payload(full_conversation="Assistant: Hi"))
    body = _texts(blocks)
    assert "Transcript" in body
    assert "Summary" not in body
    assert "Sentiment" not in body


def test_summary_sentiment_and_extraction_render_when_present() -> None:
    _, blocks = post_call_blocks(
        _payload(
            call_summary="Candidate has 5 years of BIM experience.",
            sentiment_analysis={"label": "positive", "score": 0.8, "rationale": "keen"},
            extracted_information={"full_name": "Manikanta", "notice_period": "1 month"},
        )
    )
    body = _texts(blocks)
    assert "5 years of BIM" in body
    assert "positive" in body and "keen" in body
    assert "Manikanta" in body and "1 month" in body


def test_extraction_omits_empty_values() -> None:
    _, blocks = post_call_blocks(
        _payload(extracted_information={"full_name": "Aisha", "salary_expectation": None})
    )
    body = _texts(blocks)
    assert "Aisha" in body
    assert "salary_expectation" not in body


def test_empty_extraction_says_so_rather_than_rendering_blank() -> None:
    _, blocks = post_call_blocks(_payload(extracted_information={"full_name": None}))
    assert "Nothing found" in _texts(blocks)


def test_contact_block_renders_when_supplied() -> None:
    _, blocks = post_call_blocks(_payload(contact={"phone": "+917502163963", "name": "Yacoob"}))
    body = _texts(blocks)
    assert "+917502163963" in body and "Yacoob" in body


def test_long_transcript_is_truncated_not_dropped() -> None:
    # Slack rejects an oversized block outright, which would lose the summary
    # sitting above it too.
    _, blocks = post_call_blocks(
        _payload(call_summary="Short summary.", full_conversation="x" * 20_000)
    )
    body = _texts(blocks)
    assert "Short summary." in body
    assert "truncated" in body
    for block in blocks:
        text = block.get("text")
        if isinstance(text, dict):
            assert len(text["text"]) <= MAX_BLOCK_CHARS


# --- Config validation for the slack delivery method ---


def _config(**kwargs) -> PostCallConfig:
    base = {
        "tenant_id": TenantId(new_id()),
        "chatbot_id": ChatbotId(new_id()),
        "delivery_method": "slack",
    }
    return PostCallConfig(**{**base, **kwargs})


def test_slack_config_needs_no_destination_of_its_own() -> None:
    # The channel comes from the tenant's Slack integration, so rotating that
    # one webhook fixes every post-call rule at once.
    config = _config()
    assert not config.requires_destination()
    assert config.validation_error() is None


def test_slack_destination_is_descriptive() -> None:
    assert "Slack" in _config().destination()


def test_slack_still_requires_triggers_and_content() -> None:
    assert "at least one call status" in (_config(trigger_statuses=[]).validation_error() or "")
    empty = _config(
        include_summary=False,
        include_transcript=False,
        include_sentiment=False,
        include_extracted=False,
    )
    assert "at least one item to include" in (empty.validation_error() or "")


@pytest.mark.parametrize("method", ["webhook", "email"])
def test_other_methods_still_require_a_destination(method: str) -> None:
    config = _config(delivery_method=method, webhook_url="", email_to="")
    assert config.requires_destination()
    assert config.validation_error() is not None
