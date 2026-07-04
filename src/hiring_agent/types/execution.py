"""Hiring Agent — plan execution + human-approval types.

The Executor consumes a plan (from the Planner) and runs its steps one at a
time. When it reaches a sensitive step (or a repeatedly-failing one) it pauses
and records a `PendingApproval`; a human resolves it via /approve or /reject.
`ExecutionCursor` is the durable slice persisted on the memory row so the run
can pause across requests.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=200)


class ApprovalRequest(BaseModel):
    run_id: UUID


class PendingApproval(BaseModel):
    step_id: int
    step_key: str
    step_name: str
    tool: str | None = None
    kind: str  # "sensitive" (gated action) | "failure" (retries exhausted)
    reason: str = ""


class ExecutionCursor(BaseModel):
    """Durable executor state persisted on the memory row."""

    goal: str = ""
    plan: list[dict] = Field(default_factory=list)  # serialized PlanStep list
    cursor: int = 0  # index of the next step to execute
    pending_approval: PendingApproval | None = None


class ExecutedTask(BaseModel):
    step: int
    tool: str | None = None
    status: str  # ok | skipped | simulated | failed | rejected
    observation: str = ""


class ExecutionState(BaseModel):
    """What the /execute, /approve, /reject endpoints return."""

    run_id: str
    goal: str
    status: str
    cursor: int
    total_steps: int
    pending_approval: PendingApproval | None = None
    executed: list[ExecutedTask] = Field(default_factory=list)
    summary: str = ""


class RunSummary(BaseModel):
    """One row in the execution-history list."""

    run_id: str
    goal: str
    status: str
    cursor: int
    total_steps: int
    created_at: str
    updated_at: str
