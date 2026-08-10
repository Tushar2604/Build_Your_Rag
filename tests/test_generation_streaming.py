"""Streaming generation: sections surface as the model writes them.

The parser is the interesting part. It reads JSON that is still being written,
so the tests feed it one character at a time — the worst case, and the one that
actually happens when a provider streams single-token chunks.
"""

from __future__ import annotations

import json

import pytest
from src.application.ports.services import LLMResult
from src.application.use_cases.generate_assistant import (
    GenerateAssistantUseCase,
    SectionStreamParser,
)

PAYLOAD = {
    "name": "Google India Hiring Assistant",
    "direction": "outgoing",
    "welcome_message": "Hi [user_name], is now a good time?",
    "sections": [
        {"title": "Identity & Purpose", "body": "You are a recruiter."},
        {"title": "Facts", "body": "- Offices in Bengaluru."},
        {"title": "Flow: qualification", "body": "1. Confirm the role."},
    ],
}


def _drip(parser: SectionStreamParser, text: str) -> list[dict]:
    """Feed one character at a time, collecting whatever completes."""
    out: list[dict] = []
    for char in text:
        out.extend(parser.feed(char))
    return out


class TestSectionStreamParser:
    def test_sections_surface_one_at_a_time(self) -> None:
        found = _drip(SectionStreamParser(), json.dumps(PAYLOAD))
        assert [s["title"] for s in found] == [
            "Identity & Purpose",
            "Facts",
            "Flow: qualification",
        ]

    def test_a_section_appears_only_once_it_is_complete(self) -> None:
        """A half-written body must not be shown and then corrected — that
        reads as the assistant changing its mind."""
        parser = SectionStreamParser()
        head = '{"sections": [{"title": "Identity & Purpose", "body": "You are a rec'
        assert parser.feed(head) == []
        assert [s["title"] for s in parser.feed('ruiter."}')] == ["Identity & Purpose"]

    def test_braces_inside_a_body_do_not_end_the_section(self) -> None:
        payload = {"sections": [{"title": "T", "body": "Use {braces} and [brackets]."}]}
        found = _drip(SectionStreamParser(), json.dumps(payload))
        assert len(found) == 1
        assert found[0]["body"] == "Use {braces} and [brackets]."

    def test_escaped_quotes_inside_a_body_do_not_end_the_section(self) -> None:
        payload = {"sections": [{"title": "T", "body": 'Say "hello" warmly.'}]}
        found = _drip(SectionStreamParser(), json.dumps(payload))
        assert len(found) == 1
        assert found[0]["body"] == 'Say "hello" warmly.'

    def test_head_fields_are_reported_once_all_three_arrive(self) -> None:
        parser = SectionStreamParser()
        parser.feed('{"name": "Acme", "direction": "incoming"')
        assert parser.meta() is None, "incomplete meta must not be emitted"

        parser.feed(', "welcome_message": "Hello!", "sections": [')
        assert parser.meta() == {
            "name": "Acme",
            "direction": "incoming",
            "welcome_message": "Hello!",
        }
        # Emitted at most once, so the UI is not told the name twice.
        assert parser.meta() is None

    def test_prose_before_the_json_is_ignored(self) -> None:
        found = _drip(SectionStreamParser(), "Sure! Here you go:\n" + json.dumps(PAYLOAD))
        assert len(found) == 3


class StreamingLLM:
    """Streams a canned reply in small chunks, or fails."""

    name = "stub"

    def __init__(self, text: str = "", *, fail: bool = False, chunk: int = 7) -> None:
        self._text = text
        self._fail = fail
        self._chunk = chunk

    async def generate(self, system: str, user: str) -> LLMResult:
        return LLMResult(text=self._text, tokens_used=1, provider="stub", model="stub")

    async def stream(self, system, user, on_provider=None):  # type: ignore[no-untyped-def]
        if self._fail:
            raise RuntimeError("provider is down")
        for i in range(0, len(self._text), self._chunk):
            yield self._text[i : i + self._chunk]


async def _collect(llm, description="call candidates about engineering roles", **kw):
    events = []
    async for kind, payload in GenerateAssistantUseCase(llm).stream(description, **kw):
        events.append((kind, payload))
    return events


class TestStreamingUseCase:
    async def test_meta_then_sections_then_the_blueprint(self) -> None:
        events = await _collect(StreamingLLM(json.dumps(PAYLOAD)))
        kinds = [k for k, _ in events]

        assert kinds[0] == "meta"
        assert kinds[-1] == "blueprint"
        assert kinds.count("section") == 3

    def _blueprint(self, events):
        return next(p for k, p in events if k == "blueprint")

    async def test_the_blueprint_is_validated_not_just_the_stream(self) -> None:
        """Streamed sections are for display; the saved blueprint still gets
        the spine ordering and the guardrails backstop."""
        scrambled = dict(PAYLOAD)
        scrambled["sections"] = list(reversed(PAYLOAD["sections"]))
        events = await _collect(StreamingLLM(json.dumps(scrambled)))

        streamed = [p["title"] for k, p in events if k == "section"]
        assert streamed[0] == "Flow: qualification", "display order follows the model"

        saved = [s.title for s in self._blueprint(events).sections]
        assert saved == ["Identity & Purpose", "Facts", "Flow: qualification", "Guardrails"]

    async def test_a_provider_outage_still_ends_with_a_usable_draft(self) -> None:
        events = await _collect(StreamingLLM(fail=True))
        blueprint = self._blueprint(events)

        assert blueprint.ai_generated is False
        assert blueprint.sections
        assert blueprint.sections[-1].title == "Guardrails"

    @pytest.mark.parametrize("bad", ["not json", "{}", '{"sections": []}'])
    async def test_unusable_output_falls_back(self, bad: str) -> None:
        blueprint = self._blueprint(await _collect(StreamingLLM(bad)))
        assert blueprint.ai_generated is False
        assert blueprint.sections

    async def test_regenerating_keeps_the_existing_name(self) -> None:
        events = await _collect(
            StreamingLLM(json.dumps(PAYLOAD)), existing_name="Recruiting Bot"
        )
        assert self._blueprint(events).name == "Recruiting Bot"

    async def test_a_chunky_provider_produces_the_same_sections(self) -> None:
        """Chunk size is a provider detail and must not change the result."""
        for chunk in (1, 3, 50, 5000):
            events = await _collect(StreamingLLM(json.dumps(PAYLOAD), chunk=chunk))
            assert [p["title"] for k, p in events if k == "section"] == [
                "Identity & Purpose",
                "Facts",
                "Flow: qualification",
            ], f"chunk size {chunk} changed the output"
