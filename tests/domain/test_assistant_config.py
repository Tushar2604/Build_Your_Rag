"""Assistant runtime settings and how the welcome message reaches a caller."""

from __future__ import annotations

import pytest
from src.domain.chatbot.entities import (
    MAX_WELCOME_MESSAGE,
    OPENER_INSTRUCTION,
    AssistantConfig,
    opener_instruction,
    static_welcome,
)


def test_defaults_are_a_working_assistant() -> None:
    config = AssistantConfig().normalized()

    assert config.direction == "outgoing"
    assert config.languages == ["English (India)"]
    assert config.tts_voice and config.llm_model and config.stt_model


def test_an_unknown_direction_is_rejected() -> None:
    assert AssistantConfig(direction="sideways").normalized().direction == "outgoing"


def test_duplicate_languages_are_removed_but_order_is_kept() -> None:
    # The UI renders these as an ordered list; a repeat reads as a bug.
    config = AssistantConfig(languages=["Hindi", "English (US)", "Hindi"]).normalized()
    assert config.languages == ["Hindi", "English (US)"]


def test_an_empty_language_list_falls_back() -> None:
    # An assistant with no language has nothing to transcribe or speak in.
    assert AssistantConfig(languages=["", "  "]).normalized().languages == ["English (India)"]


def test_a_long_welcome_message_is_truncated_not_rejected() -> None:
    config = AssistantConfig(welcome_message="x" * (MAX_WELCOME_MESSAGE + 500)).normalized()
    assert len(config.welcome_message) == MAX_WELCOME_MESSAGE


def test_variables_are_substituted_into_the_welcome() -> None:
    config = AssistantConfig(welcome_message="Hi [user_name], this is [company].")
    rendered = config.render_welcome({"user_name": "Asha", "company": "Acme"})
    assert rendered == "Hi Asha, this is Acme."


def test_an_unknown_variable_is_left_visible() -> None:
    """A visible `[user_name]` tells the operator their variable never got wired
    up; a silent "Hi ," just looks broken to the caller."""
    config = AssistantConfig(welcome_message="Hi [user_name], welcome.")
    assert config.render_welcome({}) == "Hi [user_name], welcome."
    assert config.render_welcome({"user_name": ""}) == "Hi [user_name], welcome."


class TestOpener:
    def test_dynamic_off_speaks_the_message_verbatim(self) -> None:
        # Turning Dynamic off means "say exactly this" — so the text is returned
        # directly and the generation call is skipped entirely.
        config = AssistantConfig(welcome_message="Hello there.", welcome_dynamic=False)
        assert static_welcome(config) == "Hello there."

    def test_dynamic_off_still_fills_variables(self) -> None:
        config = AssistantConfig(welcome_message="Hi [user_name].", welcome_dynamic=False)
        assert static_welcome(config, {"user_name": "Asha"}) == "Hi Asha."

    @pytest.mark.parametrize(
        "config",
        [
            AssistantConfig(welcome_message="Hello.", welcome_dynamic=True),
            AssistantConfig(welcome_message="", welcome_dynamic=False),
            AssistantConfig(welcome_message="", welcome_dynamic=True),
        ],
    )
    def test_everything_else_goes_through_the_model(self, config: AssistantConfig) -> None:
        assert static_welcome(config) is None

    def test_a_dynamic_welcome_becomes_the_brief_not_the_script(self) -> None:
        config = AssistantConfig(welcome_message="Ask if now is a good time.", welcome_dynamic=True)
        instruction = opener_instruction(config)

        assert "Ask if now is a good time." in instruction
        assert "own words" in instruction
        assert instruction != OPENER_INSTRUCTION

    def test_no_welcome_message_uses_the_stock_opener(self) -> None:
        assert opener_instruction(AssistantConfig()) == OPENER_INSTRUCTION


class TestResponseLanguage:
    """The operator's own control over what the assistant writes back in — see
    `RESPONSE_LANGUAGE_AUTO` and `domain/safety/guardrails.language_rules`.
    """

    def test_the_default_is_english_not_auto_mirror(self) -> None:
        # A brand-new assistant's out-of-the-box behaviour, per the direct
        # request this replaced: "the default should be English, pure
        # English" — not silently mirroring whatever a customer writes.
        assert AssistantConfig().normalized().response_language == "English (India)"

    def test_a_valid_choice_is_kept(self) -> None:
        config = AssistantConfig(response_language="Hindi").normalized()
        assert config.response_language == "Hindi"

    def test_auto_mirror_is_still_a_selectable_choice(self) -> None:
        from src.domain.chatbot.entities import RESPONSE_LANGUAGE_AUTO

        config = AssistantConfig(response_language=RESPONSE_LANGUAGE_AUTO).normalized()
        assert config.response_language == RESPONSE_LANGUAGE_AUTO

    def test_an_unknown_value_falls_back_to_english(self) -> None:
        config = AssistantConfig(response_language="Klingon").normalized()
        assert config.response_language == "English (India)"

    def test_an_empty_value_falls_back_to_english(self) -> None:
        assert AssistantConfig(response_language="  ").normalized().response_language == (
            "English (India)"
        )
