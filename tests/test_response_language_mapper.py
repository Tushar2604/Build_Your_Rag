"""The backward-compatibility property that matters most for this setting:
a chatbot row written before `response_language` existed must keep behaving
exactly as it always did — auto-mirroring the customer — not silently switch
to English the next time it is read.

A brand-new row, or one already re-saved with an explicit choice, is the
opposite case: it must NOT be coerced back to auto-mirror just because English
happens to be the fresh-default value. Both directions are real regressions a
single "just default the missing key" line could produce, so both are pinned.

No database: `ChatbotModel` is instantiated directly (SQLAlchemy declarative
models accept their columns as constructor kwargs), which is enough to drive
the mapper function itself.
"""

from __future__ import annotations

import uuid

from src.domain.chatbot.entities import RESPONSE_LANGUAGE_AUTO
from src.infrastructure.persistence.mappers import (
    assistant_config_to_jsonb,
    chatbot_to_domain,
)
from src.infrastructure.persistence.models import ChatbotModel


def _row(assistant_config: dict) -> ChatbotModel:
    return ChatbotModel(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Test Assistant",
        display_id=1,
        channel="text",
        system_prompt="You are a helpful assistant.",
        flow_sections=[],
        retrieval={},
        assistant_config=assistant_config,
        allowed_document_ids=[],
        is_public=False,
        public_key="pk_test",
        allowed_origins=[],
        widget_config={},
        voice_profile_id=None,
    )


class TestARowFromBeforeThisSettingExisted:
    def test_a_missing_key_falls_back_to_auto_mirror_not_english(self) -> None:
        # The exact shape of every row persisted before this field was added:
        # the key is simply absent, since it was never written.
        bot = chatbot_to_domain(_row({"direction": "outgoing", "tts_voice": "Cartesia - Riya"}))

        assert bot.assistant.response_language == RESPONSE_LANGUAGE_AUTO

    def test_an_empty_assistant_config_blob_also_falls_back_to_auto(self) -> None:
        bot = chatbot_to_domain(_row({}))

        assert bot.assistant.response_language == RESPONSE_LANGUAGE_AUTO


class TestARowThatAlreadyHasAnExplicitChoice:
    def test_a_saved_english_choice_is_read_back_as_english(self) -> None:
        bot = chatbot_to_domain(_row({"response_language": "English (India)"}))

        assert bot.assistant.response_language == "English (India)"

    def test_a_saved_specific_language_is_read_back_unchanged(self) -> None:
        bot = chatbot_to_domain(_row({"response_language": "Hindi"}))

        assert bot.assistant.response_language == "Hindi"

    def test_a_saved_auto_choice_is_read_back_as_auto(self) -> None:
        # An operator who explicitly picked "match the customer" must get
        # exactly that back, indistinguishable from a legacy row only by
        # coincidence of value — not something the mapper should special-case.
        bot = chatbot_to_domain(_row({"response_language": RESPONSE_LANGUAGE_AUTO}))

        assert bot.assistant.response_language == RESPONSE_LANGUAGE_AUTO


class TestRoundTripping:
    def test_writing_then_reading_preserves_the_choice(self) -> None:
        from src.domain.chatbot.entities import AssistantConfig

        for choice in ("English (India)", "Hindi", RESPONSE_LANGUAGE_AUTO, "Spanish"):
            written = assistant_config_to_jsonb(AssistantConfig(response_language=choice))
            bot = chatbot_to_domain(_row(written))
            assert bot.assistant.response_language == choice

    def test_a_fresh_default_config_writes_english_explicitly(self) -> None:
        # So that re-saving a brand-new assistant never regresses to the
        # legacy-row fallback path later — the key is always present once
        # anything has been written through this mapper at all.
        from src.domain.chatbot.entities import AssistantConfig

        written = assistant_config_to_jsonb(AssistantConfig())
        assert written["response_language"] == "English (India)"
