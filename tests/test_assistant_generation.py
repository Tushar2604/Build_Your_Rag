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
    _SYSTEM,
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


class TestRecruitingIsAFirstClassUseCase:
    """The reported failure: describing a hiring/recruiting assistant produced
    a noticeably weaker flow than every other category, because every other
    category had a hint steering the model toward a concrete structure and
    recruiting — this platform's own most common assistant — had none at all.
    """

    def test_a_recruiting_hint_exists(self) -> None:
        from src.application.use_cases.generate_assistant import USE_CASE_HINTS

        assert "recruiting" in USE_CASE_HINTS

    def test_the_recruiting_hint_demands_the_name_first_sequence(self) -> None:
        from src.application.use_cases.generate_assistant import USE_CASE_HINTS

        hint = USE_CASE_HINTS["recruiting"].lower()
        assert "name" in hint
        assert "before" in hint  # name comes before diving into the role
        assert "opportunity" in hint or "role" in hint

    async def test_the_recruiting_hint_reaches_the_model(self) -> None:
        llm = StubLLM(_payload())
        await GenerateAssistantUseCase(llm).execute(
            "call candidates about a BIM engineer opening", use_case="recruiting"
        )

        _, user_prompt = llm.calls[0]
        assert "recruiting" in user_prompt.lower() or "candidate" in user_prompt.lower()

    def test_every_advertised_use_case_chip_has_a_matching_hint(self) -> None:
        # Guards the exact gap that caused this: a chip the frontend can show
        # with no hint behind it silently degrades to a generic generation.
        from src.application.use_cases.generate_assistant import USE_CASE_HINTS
        from src.interfaces.api.routers.chatbots import _USE_CASE_LABELS

        missing = [key for key in _USE_CASE_LABELS if key not in USE_CASE_HINTS]
        assert missing == [], f"these chips have no generator hint: {missing}"


class TestEveryGeneratedFlowAsksWhoItIsTalkingToFirst:
    """Not just recruiting: any generated assistant that has no name to work
    with should get to know who it's speaking to before it gets down to
    business — the shape of a real conversation, not a form."""

    def test_the_system_prompt_instructs_asking_for_a_name_when_unknown(self) -> None:
        from src.application.use_cases.generate_assistant import _SYSTEM

        lowered = _SYSTEM.lower()
        assert "asking for their name" in lowered or "name warmly" in lowered

    def test_the_instruction_does_not_apply_when_a_name_is_already_known(self) -> None:
        # Must not invent a redundant "what's your name" step for a call where
        # the operator already has one — that is a worse, not better, opener.
        from src.application.use_cases.generate_assistant import _SYSTEM

        lowered = _SYSTEM.lower()
        assert "already has a name" in lowered or "never invent this step" in lowered


class TestQualityDoesNotDependOnPickingAUseCaseChip:
    """The six use-case chips are a closed set (recruiting, lead generation,
    appointments, support, negotiation, collections) — a dental clinic, a
    college admissions office, a veterinary practice, a law firm none of them
    name a category at all. The fix cannot be "add more chips forever"; the
    base prompt itself has to reason about whatever profession the description
    actually describes, chip or no chip.
    """

    def test_the_system_prompt_demands_inferring_the_profession(self) -> None:
        lowered = _SYSTEM.lower()
        assert "profession" in lowered or "real-world" in lowered

    def test_the_standard_is_explicitly_independent_of_a_use_case_hint(self) -> None:
        lowered = _SYSTEM.lower()
        assert "with or without a use-case hint" in lowered or (
            "never a reason to write" in lowered
        )

    def test_worked_examples_show_domain_specific_reasoning_not_small_talk(self) -> None:
        # Pinned loosely on purpose — these exact professions may be edited,
        # but the prompt must keep teaching the PATTERN (infer the specific
        # first question a real professional in this job would ask) rather
        # than naming only the six chip categories.
        lowered = _SYSTEM.lower()
        assert "dental" in lowered or "receptionist" in lowered

    async def test_a_dental_clinic_description_gets_no_hint_but_still_generates(
        self,
    ) -> None:
        # No use_case passed at all — the common path for a business that
        # matches none of the six chips. Generation must not degrade to
        # nothing just because USE_CASE_HINTS has nothing for it.
        llm = StubLLM(_payload(name="Bright Smile Dental Receptionist"))

        blueprint = await GenerateAssistantUseCase(llm).execute(
            "answer calls for my dental clinic and book appointments"
        )

        assert blueprint.ai_generated
        system_prompt_sent, user_prompt_sent = llm.calls[0]
        # The reasoning instruction lives in the SYSTEM prompt, sent on every
        # call regardless of use_case — this is the property that makes it
        # apply universally rather than only to the six named categories.
        assert "profession" in system_prompt_sent.lower()
        assert "dental clinic" in user_prompt_sent.lower()

    def test_the_detail_ceiling_was_raised_for_super_detailed_bodies(self) -> None:
        # The reported complaint was thin, generic output — a 1200-character
        # ceiling was part of why. Confirms the guidance actually changed
        # rather than only the reasoning instruction being added on top of it.
        assert "1200 characters" not in _SYSTEM
