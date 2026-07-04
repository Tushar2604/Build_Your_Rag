"""Hiring Agent — request controllers.

Thin handlers that validate incoming data, call a service, and return a
response model. Controllers must not contain business logic; all
orchestration belongs in services. Every controller injects
`current_principal` from `src.interfaces.api.deps` for auth.
"""

from __future__ import annotations

from uuid import UUID

from src.domain.shared.identifiers import TenantId
from src.hiring_agent.persistence.repository import HiringMemoryRepository
from src.hiring_agent.services import WorkflowEngine
from src.hiring_agent.services.executor import Executor
from src.hiring_agent.services.memory_store import HiringMemoryStore
from src.hiring_agent.services.planner import Planner
from src.hiring_agent.tools import hiring_registry
from src.hiring_agent.types import ExecutionPlan, WorkflowRunRequest, WorkflowRunResponse
from src.hiring_agent.types.execution import ExecutionState, RunSummary
from src.hiring_agent.types.memory import HiringAgentMemory

# Persistent memory store (reuses the shared DB sessionmaker, resolved lazily).
# Wiring it into the engine makes every run durable and resumable.
_memory_store = HiringMemoryStore(HiringMemoryRepository())

# Stateless engine with the module-level tool registry — safe as a singleton.
_engine = WorkflowEngine(hiring_registry, memory_store=_memory_store)

# Stateless planner — safe as a module-level singleton.
_planner = Planner()

# Plan-driven executor: connects the planner to the tool registry, one task at
# a time, with human-approval gating. Shares the persistent memory store.
_executor = Executor(hiring_registry, _memory_store, _planner)


async def run_workflow(
    request: WorkflowRunRequest, tenant_id: TenantId
) -> WorkflowRunResponse:
    """Delegate to the workflow engine with the caller's tenant scope."""
    return await _engine.run(request.start_from, tenant_id)


async def resume_workflow(run_id: UUID, tenant_id: TenantId) -> WorkflowRunResponse:
    """Resume a previously interrupted run from its last persisted state."""
    return await _engine.resume(tenant_id, run_id)


def create_plan(goal: str) -> ExecutionPlan:
    """Generate an execution plan for a hiring goal. Plan only — no execution."""
    return _planner.plan(goal)


async def execute_plan(goal: str, tenant_id: TenantId) -> ExecutionState:
    """Plan `goal` and execute it one task at a time (pausing at approval gates)."""
    return await _executor.start(tenant_id, goal)


async def approve_task(run_id: UUID, tenant_id: TenantId) -> ExecutionState:
    """Approve the pending task and resume execution."""
    return await _executor.approve(tenant_id, run_id)


async def reject_task(run_id: UUID, tenant_id: TenantId) -> ExecutionState:
    """Reject the pending task (skip it) and resume execution."""
    return await _executor.reject(tenant_id, run_id)


async def list_runs(tenant_id: TenantId) -> list[RunSummary]:
    """Recent hiring runs for the tenant (execution history)."""
    runs = await _memory_store.list_runs(tenant_id)
    return [
        RunSummary(
            run_id=str(m.run_id),
            goal=(m.execution.goal if m.execution else ""),
            status=m.status.value,
            cursor=(m.execution.cursor if m.execution else 0),
            total_steps=(len(m.execution.plan) if m.execution else 0),
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
        )
        for m in runs
    ]


async def get_run(run_id: UUID, tenant_id: TenantId) -> HiringAgentMemory:
    """Full persisted memory for one run (agent memory / detail view)."""
    memory = await _memory_store.get(tenant_id, run_id)
    if memory is None:
        raise LookupError(f"no hiring run {run_id}")
    return memory
