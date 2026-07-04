"""Hiring Agent — agent memory.

Manages per-session conversation history and intermediate reasoning state
for the multi-step hiring agent loop. Backed by the existing PostgreSQL
store via the chat infrastructure; no new tables at this stage.

At this stage: in-memory ring buffer for recent workflow runs.
Replaced by a proper repository when the DB layer lands.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from src.hiring_agent.types import LogEntry, WorkflowState


@dataclass
class WorkflowRun:
    run_id: str
    start_state: WorkflowState
    end_state: WorkflowState
    log: list[LogEntry]


class InMemoryWorkflowHistory:
    """Ring buffer of recent workflow runs. Cleared on process restart."""

    def __init__(self, max_runs: int = 50) -> None:
        self._runs: deque[WorkflowRun] = deque(maxlen=max_runs)

    def record(self, run: WorkflowRun) -> None:
        self._runs.appendleft(run)

    def recent(self, limit: int = 10) -> list[WorkflowRun]:
        return list(self._runs)[:limit]


# Module-level singleton — one history per process, shared across requests.
workflow_history = InMemoryWorkflowHistory()
