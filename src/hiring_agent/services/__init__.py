"""Hiring Agent — application services.

Orchestrates tools, memory, and LLM calls to fulfil hiring use-cases.
Services receive their dependencies via constructor injection; they
never import from controllers or routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog

from src.application.agent.registry import ToolRegistry
from src.application.agent.tools import ToolContext
from src.domain.shared.identifiers import TenantId
from src.hiring_agent.memory import WorkflowRun, workflow_history
from src.hiring_agent.services.memory_store import HiringMemoryStore
from src.hiring_agent.types import LogEntry, WorkflowRunResponse, WorkflowState
from src.hiring_agent.types.memory import HiringAgentMemory, HiringMemoryStatus

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[WorkflowState, WorkflowState] = {
    WorkflowState.IDLE: WorkflowState.READ_JOB,
    WorkflowState.READ_JOB: WorkflowState.SEARCH_CANDIDATES,
    WorkflowState.SEARCH_CANDIDATES: WorkflowState.RANK,
    WorkflowState.RANK: WorkflowState.SCHEDULE,
    WorkflowState.SCHEDULE: WorkflowState.EMAIL,
    WorkflowState.EMAIL: WorkflowState.COLLECT_FEEDBACK,
    WorkflowState.COLLECT_FEEDBACK: WorkflowState.SHORTLIST,
    WorkflowState.SHORTLIST: WorkflowState.COMPLETE,
    WorkflowState.COMPLETE: WorkflowState.COMPLETE,
}

# Maps each state to (tool_name, kwargs). None = no tool, use fallback message.
_STATE_TOOL_MAP: dict[WorkflowState, tuple[str | None, dict[str, Any]]] = {
    WorkflowState.IDLE: (None, {}),
    WorkflowState.READ_JOB: ("read_job", {"job_id": "job-001"}),
    WorkflowState.SEARCH_CANDIDATES: (
        "search_candidates",
        {"job_id": "job-001", "top_k": 10, "min_score": 0.60},
    ),
    WorkflowState.RANK: ("rank_candidates", {"job_id": "job-001", "top_n": 10}),
    WorkflowState.SCHEDULE: ("schedule_interview", {"job_id": "job-001", "top_n": 10}),
    WorkflowState.EMAIL: ("send_email", {"template": "interview_invite", "top_n": 10}),
    WorkflowState.COLLECT_FEEDBACK: ("collect_feedback", {"job_id": "job-001"}),
    WorkflowState.SHORTLIST: ("generate_shortlist", {"job_id": "job-001", "top_n": 3}),
    WorkflowState.COMPLETE: (None, {}),
}

# Fallback messages for states that have no registered tool.
_FALLBACK_MESSAGES: dict[WorkflowState, str] = {
    WorkflowState.IDLE: (
        "Workflow initialized. Candidate pipeline cleared and ready to accept a "
        "job description."
    ),
    WorkflowState.COMPLETE: (
        "Workflow complete. Hiring summary report ready. 3 candidates "
        "shortlisted from 47 initial matches."
    ),
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Autonomous hiring workflow state machine.

    Each active state delegates its work to a registered Tool. The engine never
    contains business logic — it drives transitions and records each tool's
    observation as the execution log entry.

    When a `memory_store` is supplied, every step is persisted to the database,
    which (a) durably captures the run's memory and (b) makes the run resumable:
    an interruption leaves a non-terminal row that `resume()` can continue.
    Persistence is best-effort — a storage hiccup never breaks the workflow.
    """

    def __init__(
        self, registry: ToolRegistry, memory_store: HiringMemoryStore | None = None
    ) -> None:
        self._registry = registry
        self._memory_store = memory_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self, start_from: WorkflowState, tenant_id: TenantId
    ) -> WorkflowRunResponse:
        memory = await self._safe_start(tenant_id, start_from)
        return await self._execute(memory, start_from, tenant_id)

    async def resume(
        self, tenant_id: TenantId, run_id: UUID
    ) -> WorkflowRunResponse:
        """Resume an interrupted run from its last persisted state."""
        if self._memory_store is None:
            raise RuntimeError("resume requires a memory store")
        memory = await self._memory_store.get(tenant_id, run_id)
        if memory is None:
            raise LookupError(f"no resumable hiring run {run_id}")

        start_from = WorkflowState(memory.current_state)
        memory.status = HiringMemoryStatus.RUNNING
        log.info(
            "hiring.workflow.resume",
            run_id=str(run_id),
            from_state=memory.current_state,
            completed=len(memory.completed_steps),
        )
        return await self._execute(memory, start_from, tenant_id)

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def _execute(
        self,
        memory: HiringAgentMemory | None,
        start_from: WorkflowState,
        tenant_id: TenantId,
    ) -> WorkflowRunResponse:
        ctx = ToolContext(tenant_id=tenant_id, chatbot_id=None)
        log_entries: list[LogEntry] = []
        # Continue step numbering across a resume so the persisted history stays
        # monotonic.
        step = len(memory.completed_steps) if memory else 0
        current = start_from

        try:
            while current != WorkflowState.COMPLETE:
                next_state = _TRANSITIONS[current]
                tool_name, message, data = await self._run_state(current, ctx)
                log_entries.append(
                    self._entry(step, current, next_state, tool_name, message)
                )
                await self._persist_step(
                    memory, step, current, next_state, tool_name, message, data
                )
                step += 1
                current = next_state

            # Terminal COMPLETE entry.
            done = WorkflowState.COMPLETE
            tool_name, terminal_msg, data = await self._run_state(done, ctx)
            log_entries.append(
                self._entry(step, done, done, tool_name, terminal_msg)
            )
            await self._persist_step(
                memory, step, done, done, tool_name, terminal_msg, data
            )
            await self._safe_complete(memory)
        except Exception as exc:  # noqa: BLE001 - mark interrupted, then re-raise
            await self._safe_interrupt(memory, str(exc))
            raise

        workflow_history.record(
            WorkflowRun(
                run_id=str(memory.run_id) if memory else str(uuid4()),
                start_state=start_from,
                end_state=WorkflowState.COMPLETE,
                log=log_entries,
            )
        )

        return WorkflowRunResponse(
            current_state=start_from,
            next_state=WorkflowState.COMPLETE,
            execution_log=log_entries,
            run_id=str(memory.run_id) if memory else None,
        )

    async def _run_state(
        self, state: WorkflowState, ctx: ToolContext
    ) -> tuple[str | None, str, dict[str, Any]]:
        """Run the tool for a state. Returns (tool_name, message, data)."""
        tool_name, kwargs = _STATE_TOOL_MAP[state]
        if tool_name is None:
            return None, _FALLBACK_MESSAGES.get(state, f"State {state.value} entered."), {}

        tool = self._registry.get(tool_name)
        if tool is None:
            return tool_name, f"[warning] No tool registered for state {state.value}.", {}

        result = await tool.run(ctx, **kwargs)
        message = result.observation if result.ok else f"[tool error] {result.observation}"
        return tool_name, message, (result.data or {})

    @staticmethod
    def _entry(
        step: int,
        from_state: WorkflowState,
        to_state: WorkflowState,
        tool_name: str | None,
        message: str,
    ) -> LogEntry:
        return LogEntry(
            step=step,
            from_state=from_state,
            to_state=to_state,
            tool_name=tool_name,
            message=message,
            timestamp=datetime.now(UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # Best-effort persistence (never breaks the workflow)
    # ------------------------------------------------------------------

    async def _safe_start(
        self, tenant_id: TenantId, start_from: WorkflowState
    ) -> HiringAgentMemory | None:
        if self._memory_store is None:
            return None
        try:
            return await self._memory_store.start_run(tenant_id, start_from.value)
        except Exception:  # noqa: BLE001
            log.warning("hiring.memory.start_failed", exc_info=True)
            return None

    async def _persist_step(
        self,
        memory: HiringAgentMemory | None,
        step: int,
        from_state: WorkflowState,
        to_state: WorkflowState,
        tool_name: str | None,
        message: str,
        data: dict[str, Any],
    ) -> None:
        if memory is None or self._memory_store is None:
            return
        try:
            await self._memory_store.record_step(
                memory,
                step=step,
                from_state=from_state.value,
                to_state=to_state.value,
                tool_name=tool_name,
                observation=message,
                data=data,
            )
        except Exception:  # noqa: BLE001
            log.warning("hiring.memory.persist_failed", step=step, exc_info=True)

    async def _safe_complete(self, memory: HiringAgentMemory | None) -> None:
        if memory is None or self._memory_store is None:
            return
        try:
            await self._memory_store.complete(memory)
        except Exception:  # noqa: BLE001
            log.warning("hiring.memory.complete_failed", exc_info=True)

    async def _safe_interrupt(
        self, memory: HiringAgentMemory | None, error: str
    ) -> None:
        if memory is None or self._memory_store is None:
            return
        try:
            await self._memory_store.interrupt(memory, error)
        except Exception:  # noqa: BLE001
            log.warning("hiring.memory.interrupt_failed", exc_info=True)
