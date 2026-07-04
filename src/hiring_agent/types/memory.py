"""Hiring Agent — persistent memory types.

`HiringAgentMemory` is the durable record of a single hiring-agent run. It
captures everything needed to inspect, audit, or RESUME a run after an
interruption: the completed workflow steps, each tool's output, any LLM
reasoning, the conversation trail, and the candidate decisions taken.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from src.hiring_agent.types.execution import ExecutionCursor


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HiringMemoryStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    WAITING_APPROVAL = "waiting_approval"  # paused for a human decision
    REJECTED = "rejected"  # a human rejected a required approval and halted

    @property
    def is_resumable(self) -> bool:
        # A run that never reached a terminal state can be picked back up.
        # WAITING_APPROVAL is intentionally excluded — it needs a human, not an
        # auto-resume sweep.
        return self in (HiringMemoryStatus.RUNNING, HiringMemoryStatus.INTERRUPTED)


class HiringAgentMemory(BaseModel):
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    status: HiringMemoryStatus = HiringMemoryStatus.RUNNING
    current_state: str = "IDLE"

    completed_steps: list[dict] = Field(default_factory=list)
    tool_outputs: list[dict] = Field(default_factory=list)
    llm_reasoning: list[dict] = Field(default_factory=list)
    conversation: list[dict] = Field(default_factory=list)
    candidate_decisions: list[dict] = Field(default_factory=list)

    # Durable executor state (plan/cursor/pending approval). None for pure
    # workflow-engine runs that don't use the plan-driven executor.
    execution: ExecutionCursor | None = None

    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
