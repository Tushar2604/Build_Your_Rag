"""ORM model for hiring-agent persistent memory.

Mapped onto the shared declarative `Base` (so it reuses the same metadata,
engine, and session machinery as the rest of the app) but declared here — the
core `models.py` is left untouched. Column types are portable: JSONB / native
UUID on PostgreSQL (production), plain JSON / CHAR-backed UUID elsewhere (e.g.
SQLite in tests). The physical Postgres columns are created by migration 0005.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.database import Base

# JSONB on Postgres, generic JSON everywhere else.
_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HiringAgentMemoryModel(Base):
    __tablename__ = "hiring_agent_memory"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, index=True, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(20), default="running", index=True)
    current_state: Mapped[str] = mapped_column(sa.String(40), default="IDLE")

    completed_steps: Mapped[list] = mapped_column(_JSON, default=list)
    tool_outputs: Mapped[list] = mapped_column(_JSON, default=list)
    llm_reasoning: Mapped[list] = mapped_column(_JSON, default=list)
    conversation: Mapped[list] = mapped_column(_JSON, default=list)
    candidate_decisions: Mapped[list] = mapped_column(_JSON, default=list)

    # Executor state: {goal, plan[], cursor, pending_approval}. Nullable.
    execution: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
