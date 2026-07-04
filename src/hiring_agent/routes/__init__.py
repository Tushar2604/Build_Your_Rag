"""Hiring Agent — FastAPI router.

All hiring-agent HTTP routes are declared here and exported as `router`.
The application factory mounts this router only when
HIRING_AGENT_ENABLED=true, so it is completely invisible to existing
chatbot traffic when the flag is off.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.hiring_agent.controllers import (
    approve_task,
    create_plan,
    execute_plan,
    get_run,
    list_runs,
    reject_task,
    resume_workflow,
    run_workflow,
)
from src.hiring_agent.services.executor import ApprovalStateError
from src.hiring_agent.types import (
    ExecutionPlan,
    PlanRequest,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from src.hiring_agent.types.execution import (
    ApprovalRequest,
    ExecuteRequest,
    ExecutionState,
    RunSummary,
)
from src.hiring_agent.types.memory import HiringAgentMemory
from src.interfaces.api.deps import PrincipalDep

router = APIRouter(prefix="/hiring-agent", tags=["hiring-agent"])


@router.get("/health", include_in_schema=True)
async def hiring_health() -> dict[str, str]:
    """Liveness check for the Hiring Agent module."""
    return {"module": "hiring-agent", "status": "ok"}


@router.post("/plan", response_model=ExecutionPlan)
async def create_hiring_plan(
    request: PlanRequest,
    _principal: PrincipalDep,
) -> ExecutionPlan:
    """Generate an execution plan for a hiring goal (e.g. 'Hire a Backend Intern').

    Returns the ordered plan only — no tools are invoked and nothing is executed.
    """
    return create_plan(request.goal)


@router.post("/run", response_model=WorkflowRunResponse)
async def run_hiring_workflow(
    request: WorkflowRunRequest,
    principal: PrincipalDep,
) -> WorkflowRunResponse:
    """Run the autonomous hiring workflow simulation.

    Traverses all states from `start_from` (default IDLE) to COMPLETE.
    Each state delegates to a registered Tool; all responses are mocked.
    No external APIs are called. The run is persisted; the response `run_id`
    can be used to resume it if interrupted.
    """
    return await run_workflow(request, principal.tenant_id)


@router.post("/resume/{run_id}", response_model=WorkflowRunResponse)
async def resume_hiring_workflow(
    run_id: UUID,
    principal: PrincipalDep,
) -> WorkflowRunResponse:
    """Resume a previously interrupted hiring run from its last persisted state."""
    try:
        return await resume_workflow(run_id, principal.tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/execute", response_model=ExecutionState)
async def execute_hiring_plan(
    request: ExecuteRequest,
    principal: PrincipalDep,
) -> ExecutionState:
    """Plan a hiring goal and execute it one task at a time.

    Sensitive actions (Send Email, Reject Candidate, Offer Letter, Notify HR)
    pause the run for human approval — the response `pending_approval` names the
    gated step; resolve it with POST /approve or POST /reject.
    """
    return await execute_plan(request.goal, principal.tenant_id)


@router.post("/approve", response_model=ExecutionState)
async def approve_hiring_task(
    request: ApprovalRequest,
    principal: PrincipalDep,
) -> ExecutionState:
    """Approve the pending task and resume execution."""
    try:
        return await approve_task(request.run_id, principal.tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/reject", response_model=ExecutionState)
async def reject_hiring_task(
    request: ApprovalRequest,
    principal: PrincipalDep,
) -> ExecutionState:
    """Reject the pending task (skip it) and resume execution."""
    try:
        return await reject_task(request.run_id, principal.tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs", response_model=list[RunSummary])
async def list_hiring_runs(_principal: PrincipalDep) -> list[RunSummary]:
    """Execution history — recent hiring runs for the tenant."""
    return await list_runs(_principal.tenant_id)


@router.get("/runs/{run_id}", response_model=HiringAgentMemory)
async def get_hiring_run(run_id: UUID, principal: PrincipalDep) -> HiringAgentMemory:
    """Full agent memory for one run (timeline, tool logs, rankings, decisions)."""
    try:
        return await get_run(run_id, principal.tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
