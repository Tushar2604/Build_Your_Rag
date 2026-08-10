"""Assistant runtime settings (direction, languages, TTS/LLM/STT, welcome message)

One JSONB column rather than eight scalar ones. These values are only ever read
whole, alongside the chatbot row they configure — nothing filters or joins on
them — and the set grows every time a voice/LLM/transcription provider is added.
A column each would mean a migration per provider for no query benefit.

Existing rows get the defaults via server_default so the app can read them before
anything has been saved through the new builder.

Revision ID: 0017_assistant_config
Revises: 0016_whatsapp_web_sessions
Create Date: 2026-08-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0017_assistant_config"
down_revision: str | None = "0016_whatsapp_web_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT = (
    '{"direction": "outgoing", "languages": ["English (India)"], '
    '"tts_voice": "Cartesia - Riya", "llm_model": "gpt-4.1-mini", '
    '"stt_model": "Soniox", "welcome_message": "", '
    '"welcome_dynamic": true, "welcome_interruptible": false}'
)


def upgrade() -> None:
    op.add_column(
        "chatbots",
        sa.Column(
            "assistant_config",
            pg.JSONB,
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbots", "assistant_config")
