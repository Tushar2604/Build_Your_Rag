"""Unit tests for post-call payload assembly: transcript rendering, which blocks
get built, and tolerance of malformed LLM JSON."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from src.application.use_cases.post_call import (
    BuildPostCallPayload,
    _parse_json_block,
    render_transcript,
)
from src.domain.chat.entities import Message, MessageRole
from src.domain.postcall.entities import PostCallConfig
from src.domain.shared.identifiers import ChatbotId, SessionId, TenantId, new_id


@dataclass
class _Result:
    text: str
    tokens_used: int = 10
    provider: str = "stub"
    model: str = "stub"


class _StubLLM:
    """Records prompts and replies with canned text, so a payload test never
    depends on a live provider."""

    def __init__(self, reply: str = "A summary.") -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def generate(self, system: str, user: str) -> _Result:
        self.calls.append(system)
        return _Result(text=self.reply)


class _ExplodingLLM:
    async def generate(self, system: str, user: str) -> _Result:
        raise RuntimeError("provider down")


def _messages() -> list[Message]:
    tenant, session = TenantId(new_id()), SessionId(new_id())
    at = datetime(2026, 8, 7, 9, 4, tzinfo=UTC)
    return [
        Message(
            session_id=session, tenant_id=tenant, role=MessageRole.ASSISTANT,
            content="May I ask a few questions?", created_at=at,
        ),
        Message(
            session_id=session, tenant_id=tenant, role=MessageRole.USER,
            content="Yes", created_at=at,
        ),
    ]


def _config(**kwargs) -> PostCallConfig:
    base = {
        "tenant_id": TenantId(new_id()),
        "chatbot_id": ChatbotId(new_id()),
        "webhook_url": "https://example.com/hook",
        "include_summary": False,
        "include_transcript": False,
        "include_sentiment": False,
        "include_extracted": False,
    }
    return PostCallConfig(**{**base, **kwargs})


def _build(config: PostCallConfig, llm, messages=None) -> dict:
    return asyncio.run(
        BuildPostCallPayload(llm).execute(
            config,
            chatbot_name="HR Assistant",
            session_id=SessionId(new_id()),
            call_status="completed",
            messages=_messages() if messages is None else messages,
        )
    )


# --- Transcript ---


def test_transcript_is_timestamped_and_role_labelled() -> None:
    rendered = render_transcript(_messages())
    assert "[2026-08-07 09:04:00 UTC] Assistant: May I ask a few questions?" in rendered
    assert "[2026-08-07 09:04:00 UTC] Candidate: Yes" in rendered


def test_transcript_of_an_empty_conversation_is_empty() -> None:
    assert render_transcript([]) == ""


# --- Block selection ---


def test_only_requested_blocks_are_built() -> None:
    llm = _StubLLM()
    payload = _build(_config(include_transcript=True), llm)
    assert "full_conversation" in payload
    assert "call_summary" not in payload
    assert "sentiment_analysis" not in payload
    # Unchecked boxes must cost zero LLM calls — that's the point of the flags.
    assert llm.calls == []


def test_each_analysis_block_costs_one_llm_call() -> None:
    llm = _StubLLM('{"label": "positive", "score": 0.8, "rationale": "keen"}')
    payload = _build(
        _config(include_summary=True, include_sentiment=True, include_extracted=True), llm
    )
    assert len(llm.calls) == 3
    assert payload["sentiment_analysis"]["label"] == "positive"


def test_payload_always_carries_the_outcome_envelope() -> None:
    payload = _build(_config(include_transcript=True), _StubLLM())
    assert payload["event"] == "post_call"
    assert payload["call_status"] == "completed"
    assert payload["chatbot"] == "HR Assistant"
    assert payload["message_count"] == 2


def test_empty_conversation_skips_analysis_but_still_delivers() -> None:
    # A no-answer outcome is itself the signal; there is nothing to summarize.
    llm = _StubLLM()
    payload = _build(_config(include_summary=True, include_sentiment=True), llm, messages=[])
    assert llm.calls == []
    assert payload["call_summary"] == ""
    assert payload["sentiment_analysis"] is None
    assert payload["message_count"] == 0


def test_a_failing_provider_degrades_one_block_not_the_delivery() -> None:
    payload = _build(_config(include_summary=True, include_transcript=True), _ExplodingLLM())
    assert payload["call_summary"] == ""
    assert "full_conversation" in payload


# --- JSON tolerance ---


def test_parses_a_fenced_json_reply() -> None:
    assert _parse_json_block('```json\n{"full_name": "Manikanta"}\n```') == {
        "full_name": "Manikanta"
    }


def test_parses_json_surrounded_by_chatter() -> None:
    assert _parse_json_block('Sure! {"label": "neutral"} Hope that helps.') == {
        "label": "neutral"
    }


def test_malformed_json_degrades_to_none() -> None:
    assert _parse_json_block("not json at all") is None
    assert _parse_json_block('{"unclosed": ') is None
    assert _parse_json_block("[1, 2, 3]") is None  # a list is not an extraction
