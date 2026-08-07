"""Unit tests for the Conversational Flow: FlowSection and prompt composition."""

from __future__ import annotations

from src.domain.chatbot.entities import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_FLOW_SECTIONS,
    Chatbot,
    FlowSection,
    compose_system_prompt,
    default_flow_sections,
)
from src.domain.shared.identifiers import TenantId, new_id


def _bot() -> Chatbot:
    return Chatbot(tenant_id=TenantId(new_id()), name="Recruiter")


def test_default_prompt_is_derived_from_default_sections() -> None:
    # The whole point of the refactor: the two can't drift apart.
    assert compose_system_prompt(default_flow_sections()) == DEFAULT_SYSTEM_PROMPT


def test_default_sections_have_unique_ids_per_call() -> None:
    first, second = default_flow_sections(), default_flow_sections()
    assert {s.id for s in first}.isdisjoint({s.id for s in second})


def test_new_chatbot_starts_on_the_stock_flow() -> None:
    bot = _bot()
    assert [s.title for s in bot.flow_sections][0] == "Identity & Purpose"
    assert bot.system_prompt == DEFAULT_SYSTEM_PROMPT


def test_disabled_section_is_excluded_from_the_prompt() -> None:
    sections = [
        FlowSection(title="Kept", body="keep this"),
        FlowSection(title="Dropped", body="secret behaviour", enabled=False),
    ]
    composed = compose_system_prompt(sections)
    assert "keep this" in composed
    assert "secret behaviour" not in composed
    assert "Dropped" not in composed


def test_empty_bodied_section_contributes_nothing() -> None:
    composed = compose_system_prompt(
        [FlowSection(title="Blank", body="   "), FlowSection(title="Real", body="hello")]
    )
    assert composed == "## Real\nhello"


def test_section_order_is_prompt_order() -> None:
    composed = compose_system_prompt(
        [FlowSection(title="B", body="second"), FlowSection(title="A", body="first")]
    )
    assert composed.index("second") < composed.index("first")


def test_apply_flow_sections_recomputes_the_prompt() -> None:
    bot = _bot()
    bot.apply_flow_sections([FlowSection(title="Terse", body="Be extremely brief.")])
    assert bot.system_prompt == "## Terse\nBe extremely brief."
    assert len(bot.flow_sections) == 1


def test_apply_flow_sections_falls_back_when_nothing_would_be_sent() -> None:
    # A blank system prompt would silently un-guard the bot, so an all-empty or
    # all-disabled flow reverts to the stock prompt rather than shipping "".
    bot = _bot()
    bot.apply_flow_sections(
        [FlowSection(title="X", body=""), FlowSection(title="Y", body="hi", enabled=False)]
    )
    assert bot.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert [s.title for s in bot.flow_sections] == [s.title for s in default_flow_sections()]


def test_apply_flow_sections_caps_the_section_count() -> None:
    bot = _bot()
    bot.apply_flow_sections(
        [FlowSection(title=f"S{i}", body=f"body {i}") for i in range(MAX_FLOW_SECTIONS + 10)]
    )
    assert len(bot.flow_sections) == MAX_FLOW_SECTIONS


def test_normalized_trims_and_defaults_a_blank_title() -> None:
    section = FlowSection(title="   ", body="  content  ").normalized()
    assert section.title == "Untitled section"
    assert section.body == "content"


def test_set_raw_prompt_clears_the_flow() -> None:
    # Otherwise the editor would show a flow that isn't what the model receives.
    bot = _bot()
    bot.set_raw_prompt("You are a terse bot.")
    assert bot.system_prompt == "You are a terse bot."
    assert bot.flow_sections == []


def test_toggling_one_section_leaves_the_others_intact() -> None:
    bot = _bot()
    sections = bot.flow_sections
    sections[0].enabled = False
    bot.apply_flow_sections(sections)
    assert "Identity & Purpose" not in bot.system_prompt
    assert "Injection Resistance" in bot.system_prompt
    # Disabled sections stay in the flow so the toggle can be reversed.
    assert len(bot.flow_sections) == len(sections)
