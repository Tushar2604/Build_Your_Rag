"""Hiring Agent — execution plan types.

A `Planner` turns a natural-language goal ("Hire a Backend Intern") into an
`ExecutionPlan`: an ordered list of steps. The plan is a description of what
*would* run — it is never executed by the planner itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=200)


class PlanStep(BaseModel):
    id: int
    key: str  # stable identifier, e.g. "read_jd"
    name: str  # display name, e.g. "Read JD"
    tool: str | None = None  # registered tool that would run this step (None = no tool yet)
    description: str = ""
    depends_on: list[int] = Field(default_factory=list)
    args: dict = Field(default_factory=dict)  # kwargs passed to the tool at execution


class ExecutionPlan(BaseModel):
    goal: str
    role: str = ""
    seniority: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    summary: str = ""  # ASCII arrow chain, e.g. "Read JD -> Search Candidates -> ..."
