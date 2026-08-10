"""The description-to-assistant generator.

What matters here is not that the model is clever — it's that whatever the model
returns, the builder ends up with something structurally sound and safely
guarded, and that a provider outage produces a draft rather than a dead end.
"""

from __future__ import annotations

import json

import pytest
from src.application.ports.services import LLMResult
from src.application.use_cases.generate_assistant import (
    GUARDRAILS_BODY,
    GenerateAssistantUseCase,
    fallback_blueprint,
)


class StubLLM:
    """Returns a canned completion, or raises to simulate an outage."""

    name = "stub"

    def __init__(self, text: str = "", *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str) -> LLMResult:
        self.calls.append((system, user))
        if self._fail:
            raise RuntimeError("provider is down")
        return LLMResult(text=self._text, tokens_used=1, provider="stub", model="stub")


def _payload(**overrides) -> str:
    body = {
        "name": "Google India Hiring Assistant",
        "direction": "outgoing",
        "welcome_message": "Hi [user_name], is now a good time?",
        "sections": [
            {"title": "Identity & Purpose", "body": "You are a recruiter."},
            {"title": "Facts", "body": "- Offices in Bengaluru and Hyderabad."},
            {"title": "Actions & Limits", "body": "- CAN: confirm interest."},
            {"title": "Flow: candidate qualification", "body": "1. Confirm the role."},
            {"title": "Scope & Redirects", "body": "Stay on hiring."},
        ],
    }
    body.update(overrides)
    return json.dumps(body)


async def test_generates_an_assistant_from_a_description() -> None:
    llm = StubLLM(_payload())
    blueprint = await GenerateAssistantUseCase(llm).execute("hire engineers in India")

    assert blueprint.ai_generated
    assert blueprint.name == "Google India Hiring Assistant"
    assert blueprint.welcome_message == "Hi [user_name], is now a good time?"
    assert blueprint.direction == "outgoing"
    assert [s.title for s in blueprint.sections][:4] == [
        "Identity & Purpose",
        "Facts",
        "Actions & Limits",
        "Flow: candidate qualification",
    ]


async def test_the_use_case_hint_reaches_the_model() -> None:
    llm = StubLLM(_payload())
    await GenerateAssistantUseCase(llm).execute("chase invoices", use_case="collections")

    _, user_prompt = llm.calls[0]
    assert "collections" in user_prompt.lower() or "payment" in user_prompt.lower()


async def test_sections_are_sorted_back_onto_the_spine() -> None:
    """A model that emits sections out of order still produces a sane prompt.

    Order is not cosmetic — it is the order the model reads its own instructions
    in, so guardrails arriving before the assistant's identity reads as a
    different prompt entirely.
    """
    scrambled = _payload(
        sections=[
            {"title": "Guardrails", "body": "Custom guard."},
            {"title": "Scope & Redirects", "body": "Stay on topic."},
            {"title": "Flow: qualification", "body": "1. Ask."},
            {"title": "Facts", "body": "- A fact."},
            {"title": "Identity & Purpose", "body": "You are a rep."},
        ]
    )
    blueprint = await GenerateAssistantUseCase(StubLLM(scrambled)).execute("sell things")

    assert [s.title for s in blueprint.sections] == [
        "Identity & Purpose",
        "Facts",
        "Flow: qualification",
        "Scope & Redirects",
        "Guardrails",
    ]


async def test_guardrails_are_appended_when_the_model_omits_them() -> None:
    blueprint = await GenerateAssistantUseCase(StubLLM(_payload())).execute("do a thing")

    guards = [s for s in blueprint.sections if s.title == "Guardrails"]
    assert len(guards) == 1
    assert guards[0].body == GUARDRAILS_BODY
    # And it goes last, so nothing the model wrote can be read as overriding it.
    assert blueprint.sections[-1].title == "Guardrails"


async def test_a_models_own_guardrails_are_kept() -> None:
    payload = json.loads(_payload())
    payload["sections"].append({"title": "Guardrails", "body": "Never quote a price."})
    blueprint = await GenerateAssistantUseCase(StubLLM(json.dumps(payload))).execute("x" * 20)

    guards = [s for s in blueprint.sections if s.title == "Guardrails"]
    assert len(guards) == 1
    assert guards[0].body == "Never quote a price."


@pytest.mark.parametrize(
    "wrapper",
    [
        "```json\n{payload}\n```",
        "```\n{payload}\n```",
        "Sure! Here is the configuration:\n\n{payload}\n\nLet me know if you want changes.",
    ],
)
async def test_json_is_recovered_from_prose_and_code_fences(wrapper: str) -> None:
    """Models wrap JSON often enough that demanding a bare object would fail
    requests that actually succeeded."""
    llm = StubLLM(wrapper.format(payload=_payload()))
    blueprint = await GenerateAssistantUseCase(llm).execute("hire engineers")

    assert blueprint.ai_generated
    assert blueprint.name == "Google India Hiring Assistant"


async def test_sections_without_a_body_are_dropped() -> None:
    # A titled section with no body contributes nothing to the composed prompt
    # but still occupies a row in the editor, which reads as a bug.
    payload = _payload(
        sections=[
            {"title": "Identity & Purpose", "body": "You are a rep."},
            {"title": "Facts", "body": "   "},
            {"title": "", "body": "orphaned"},
        ]
    )
    blueprint = await GenerateAssistantUseCase(StubLLM(payload)).execute("sell things")

    assert [s.title for s in blueprint.sections] == ["Identity & Purpose", "Guardrails"]


@pytest.mark.parametrize(
    "bad_output",
    ["not json at all", "{}", '{"sections": []}', '{"sections": "nope"}', ""],
)
async def test_unusable_model_output_falls_back_to_a_draft(bad_output: str) -> None:
    blueprint = await GenerateAssistantUseCase(StubLLM(bad_output)).execute(
        "call candidates about engineering roles"
    )

    assert blueprint.ai_generated is False
    assert blueprint.sections, "a fallback must still be a usable assistant"
    assert blueprint.sections[-1].title == "Guardrails"


async def test_a_provider_outage_does_not_break_the_builder() -> None:
    blueprint = await GenerateAssistantUseCase(StubLLM(fail=True)).execute(
        "book dental appointments"
    )

    assert blueprint.ai_generated is False
    assert "Appointments" in blueprint.name or "Book" in blueprint.name


async def test_regenerating_keeps_the_existing_name() -> None:
    """Ask AI must not rename an assistant that is already deployed and linked to."""
    llm = StubLLM(_payload(name="Something Else Entirely"))
    blueprint = await GenerateAssistantUseCase(llm).execute(
        "hire engineers", existing_name="Recruiting Bot"
    )

    assert blueprint.name == "Recruiting Bot"


async def test_an_unknown_direction_falls_back_to_outgoing() -> None:
    blueprint = await GenerateAssistantUseCase(StubLLM(_payload(direction="sideways"))).execute(
        "hire engineers"
    )
    assert blueprint.direction == "outgoing"


def test_the_fallback_restates_the_operators_own_description() -> None:
    # It must not invent facts about a business it knows nothing about.
    blueprint = fallback_blueprint("chase overdue invoices politely", "collections")

    identity = next(s for s in blueprint.sections if s.title == "Identity & Purpose")
    assert "chase overdue invoices politely" in identity.body
