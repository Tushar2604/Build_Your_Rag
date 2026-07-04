"""Executor — runs a Planner-generated plan one task at a time.

Connects the Planner to the Tool Registry:

    Planner -> ExecutionPlan (tasks) -> Executor -> ToolRegistry

Guarantees:
  * Sequential: exactly one tool runs at a time (a simple await loop, plus a
    per-run lock to serialize concurrent /approve calls). Never parallel.
  * Durable: every task updates the persistent memory (the 5 buckets + cursor).
  * Resilient: a failing task is retried; if it still fails, the run pauses for
    a human decision (approve = retry, reject = skip).
  * Gated: sensitive actions (Send Email / Reject / Offer / Notify HR) require
    human approval BEFORE they run — the run pauses until /approve or /reject.
  * Observable: every step is logged.

Nothing here touches the existing chatbot; it lives entirely in the hiring
module and its own endpoints.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog

from src.application.agent.registry import ToolRegistry
from src.application.agent.tools import ToolContext, ToolResult
from src.domain.shared.identifiers import TenantId
from src.hiring_agent.services.memory_store import HiringMemoryStore
from src.hiring_agent.services.planner import Planner
from src.hiring_agent.types.execution import (
    ExecutedTask,
    ExecutionCursor,
    ExecutionState,
    PendingApproval,
)
from src.hiring_agent.types.memory import HiringAgentMemory, HiringMemoryStatus
from src.hiring_agent.types.plan import PlanStep

log = structlog.get_logger(__name__)

# Sensitive actions that require human approval BEFORE they execute.
_SENSITIVE_TOOLS = {"send_email"}
_SENSITIVE_STEP_KEYS = {"send_emails", "notify_hr", "reject_candidate", "offer_letter"}


class ApprovalStateError(Exception):
    """A /approve or /reject was issued against a run that is not awaiting one."""


class Executor:
    def __init__(
        self,
        registry: ToolRegistry,
        memory_store: HiringMemoryStore,
        planner: Planner,
        *,
        max_retries: int = 1,
    ) -> None:
        self._registry = registry
        self._memory = memory_store
        self._planner = planner
        self._max_retries = max_retries
        # Per-run locks serialize concurrent resume/approve on the same run so a
        # tool is never launched twice in parallel.
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, tenant_id: TenantId, goal: str) -> ExecutionState:
        plan = self._planner.plan(goal)
        cursor = ExecutionCursor(
            goal=goal,
            plan=[s.model_dump() for s in plan.steps],
            cursor=0,
            pending_approval=None,
        )
        first_state = plan.steps[0].key if plan.steps else "COMPLETE"
        memory = await self._memory.start_execution(tenant_id, cursor, first_state)
        log.info("executor.start", run_id=str(memory.run_id), goal=goal, steps=len(plan.steps))
        async with self._lock(memory.run_id):
            return await self._drive(memory, tenant_id)

    async def approve(self, tenant_id: TenantId, run_id: uuid.UUID) -> ExecutionState:
        return await self._decide(tenant_id, run_id, approved=True)

    async def reject(self, tenant_id: TenantId, run_id: uuid.UUID) -> ExecutionState:
        return await self._decide(tenant_id, run_id, approved=False)

    # ------------------------------------------------------------------
    # Decision handling (approve / reject)
    # ------------------------------------------------------------------

    async def _decide(
        self, tenant_id: TenantId, run_id: uuid.UUID, *, approved: bool
    ) -> ExecutionState:
        async with self._lock(run_id):
            memory = await self._memory.get(tenant_id, run_id)
            if memory is None:
                raise LookupError(f"no hiring run {run_id}")
            if memory.status != HiringMemoryStatus.WAITING_APPROVAL or memory.execution is None:
                raise ApprovalStateError(
                    f"run {run_id} is not awaiting approval (status={memory.status})"
                )

            exec_ = memory.execution
            step = self._step_at(exec_, exec_.cursor)
            ctx = ToolContext(tenant_id=tenant_id, chatbot_id=None)

            if approved:
                log.info("executor.approved", run_id=str(run_id), step=step.key, tool=step.tool)
                result = await self._run_task_with_retry(step, ctx, run_id)
                await self._record(memory, exec_.cursor, step, result)
                if not result.ok:
                    # Still failing even after approval — pause again as a failure.
                    return await self._pause(
                        memory, step, kind="failure", reason=result.observation
                    )
            else:
                log.info("executor.rejected", run_id=str(run_id), step=step.key, tool=step.tool)
                await self._memory.record_decision(
                    memory,
                    {
                        "step": step.id,
                        "action": step.key,
                        "tool": step.tool,
                        "decision": "rejected",
                    },
                )

            # Consume the pending step and continue.
            exec_.cursor += 1
            exec_.pending_approval = None
            memory.status = HiringMemoryStatus.RUNNING
            await self._memory.persist(memory)
            return await self._drive(memory, tenant_id)

    # ------------------------------------------------------------------
    # Core sequential loop
    # ------------------------------------------------------------------

    async def _drive(
        self, memory: HiringAgentMemory, tenant_id: TenantId
    ) -> ExecutionState:
        exec_ = memory.execution
        assert exec_ is not None  # guarded by callers
        ctx = ToolContext(tenant_id=tenant_id, chatbot_id=None)

        while exec_.cursor < len(exec_.plan):
            step = self._step_at(exec_, exec_.cursor)

            if self._requires_approval(step):
                return await self._pause(
                    memory,
                    step,
                    kind="sensitive",
                    reason=f"'{step.name}' requires human approval before it runs.",
                )

            result = await self._run_task_with_retry(step, ctx, memory.run_id)
            await self._record(memory, exec_.cursor, step, result)
            if not result.ok:
                return await self._pause(memory, step, kind="failure", reason=result.observation)

            exec_.cursor += 1
            memory.current_state = self._next_state(exec_)
            await self._memory.persist(memory)

        await self._memory.complete(memory)
        log.info("executor.completed", run_id=str(memory.run_id))
        return self._state(memory)

    async def _run_task_with_retry(
        self, step: PlanStep, ctx: ToolContext, run_id: uuid.UUID
    ) -> ToolResult:
        """Execute one task, retrying on failure. Exactly one tool at a time."""
        tool = self._registry.get(step.tool) if step.tool else None
        if tool is None:
            # No bound tool (e.g. Notify HR) — a simulated, benign success.
            log.info("executor.task.simulated", run_id=str(run_id), step=step.key)
            return ToolResult(
                observation=f"[simulated] {step.name} (no tool bound).",
                data={"simulated": True},
                ok=True,
            )

        attempts = self._max_retries + 1
        result = ToolResult(observation="not run", ok=False)
        for attempt in range(1, attempts + 1):
            log.info(
                "executor.task.attempt",
                run_id=str(run_id),
                step=step.key,
                tool=step.tool,
                attempt=attempt,
                of=attempts,
            )
            result = await tool.run(ctx, **(step.args or {}))
            if result.ok:
                log.info("executor.task.ok", run_id=str(run_id), step=step.key, attempt=attempt)
                return result
            log.warning(
                "executor.task.failed",
                run_id=str(run_id),
                step=step.key,
                attempt=attempt,
                observation=result.observation[:120],
            )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lock(self, run_id: uuid.UUID) -> asyncio.Lock:
        return self._locks.setdefault(str(run_id), asyncio.Lock())

    @staticmethod
    def _requires_approval(step: PlanStep) -> bool:
        return step.tool in _SENSITIVE_TOOLS or step.key in _SENSITIVE_STEP_KEYS

    @staticmethod
    def _step_at(exec_: ExecutionCursor, index: int) -> PlanStep:
        return PlanStep(**exec_.plan[index])

    @staticmethod
    def _next_state(exec_: ExecutionCursor) -> str:
        if exec_.cursor < len(exec_.plan):
            return str(exec_.plan[exec_.cursor].get("key", "COMPLETE"))
        return "COMPLETE"

    async def _record(
        self,
        memory: HiringAgentMemory,
        index: int,
        step: PlanStep,
        result: ToolResult,
    ) -> None:
        to_state = self._next_state_after(memory.execution, index)
        await self._memory.record_step(
            memory,
            step=index,
            from_state=step.key,
            to_state=to_state,
            tool_name=step.tool,
            observation=result.observation,
            data=result.data,
        )

    @staticmethod
    def _next_state_after(exec_: ExecutionCursor | None, index: int) -> str:
        if exec_ and index + 1 < len(exec_.plan):
            return str(exec_.plan[index + 1].get("key", "COMPLETE"))
        return "COMPLETE"

    async def _pause(
        self,
        memory: HiringAgentMemory,
        step: PlanStep,
        *,
        kind: str,
        reason: str,
    ) -> ExecutionState:
        memory.status = HiringMemoryStatus.WAITING_APPROVAL
        memory.execution.pending_approval = PendingApproval(
            step_id=step.id,
            step_key=step.key,
            step_name=step.name,
            tool=step.tool,
            kind=kind,
            reason=reason,
        )
        await self._memory.persist(memory)
        log.info(
            "executor.paused",
            run_id=str(memory.run_id),
            step=step.key,
            kind=kind,
            reason=reason,
        )
        return self._state(memory)

    @staticmethod
    def _state(memory: HiringAgentMemory) -> ExecutionState:
        exec_ = memory.execution
        executed = [
            ExecutedTask(
                step=o.get("step", -1),
                tool=o.get("tool"),
                status=_status_of(o),
                observation=str(o.get("observation", ""))[:200],
            )
            for o in memory.tool_outputs
        ]
        return ExecutionState(
            run_id=str(memory.run_id),
            goal=exec_.goal if exec_ else "",
            status=memory.status.value,
            cursor=exec_.cursor if exec_ else 0,
            total_steps=len(exec_.plan) if exec_ else 0,
            pending_approval=exec_.pending_approval if exec_ else None,
            executed=executed,
            summary=" -> ".join(
                str(s.get("name", s.get("key", "?"))) for s in (exec_.plan if exec_ else [])
            ),
        )


def _status_of(output: dict) -> str:
    data = output.get("data") or {}
    if data.get("simulated"):
        return "simulated"
    if data.get("skipped"):
        return "skipped"
    obs = str(output.get("observation", ""))
    if obs.startswith("[") and "error" in obs[:20].lower():
        return "failed"
    return "ok"
