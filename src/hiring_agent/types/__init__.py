"""Hiring Agent — shared type definitions.

Pydantic models, enums, and typed primitives used across controllers,
services, and tools. No external dependencies beyond the standard library
and Pydantic.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from src.hiring_agent.types.candidate_match import CandidateMatch, SearchCandidatesResult
from src.hiring_agent.types.candidate_ranking import (
    CandidateSignals,
    FactorScore,
    RankedCandidate,
    RankingResult,
    RankingWeights,
)
from src.hiring_agent.types.email import (
    EmailMessage,
    EmailTemplate,
    SendEmailBatchResult,
    SendEmailResult,
)
from src.hiring_agent.types.interview import (
    Meeting,
    MeetingRequest,
    Party,
    ScheduleInterviewResult,
)
from src.hiring_agent.types.job_context import JobContext, ReadJobResult
from src.hiring_agent.types.memory import HiringAgentMemory, HiringMemoryStatus
from src.hiring_agent.types.plan import ExecutionPlan, PlanRequest, PlanStep


class WorkflowState(StrEnum):
    IDLE = "IDLE"
    READ_JOB = "READ_JOB"
    SEARCH_CANDIDATES = "SEARCH_CANDIDATES"
    RANK = "RANK"
    SCHEDULE = "SCHEDULE"
    EMAIL = "EMAIL"
    COLLECT_FEEDBACK = "COLLECT_FEEDBACK"
    SHORTLIST = "SHORTLIST"
    COMPLETE = "COMPLETE"


class LogEntry(BaseModel):
    step: int
    from_state: WorkflowState
    to_state: WorkflowState
    tool_name: str | None = None
    message: str
    timestamp: str


class WorkflowRunRequest(BaseModel):
    start_from: WorkflowState = Field(
        default=WorkflowState.IDLE,
        description="State from which to begin the simulation. Defaults to IDLE.",
    )


class WorkflowRunResponse(BaseModel):
    current_state: WorkflowState
    next_state: WorkflowState
    execution_log: list[LogEntry]
    # Present when the run is persisted; used to resume after an interruption.
    run_id: str | None = None


__all__ = [
    "CandidateMatch",
    "CandidateSignals",
    "EmailMessage",
    "EmailTemplate",
    "ExecutionPlan",
    "FactorScore",
    "HiringAgentMemory",
    "HiringMemoryStatus",
    "JobContext",
    "LogEntry",
    "Meeting",
    "MeetingRequest",
    "Party",
    "PlanRequest",
    "PlanStep",
    "RankedCandidate",
    "RankingResult",
    "RankingWeights",
    "ReadJobResult",
    "ScheduleInterviewResult",
    "SearchCandidatesResult",
    "SendEmailBatchResult",
    "SendEmailResult",
    "WorkflowRunRequest",
    "WorkflowRunResponse",
    "WorkflowState",
]
