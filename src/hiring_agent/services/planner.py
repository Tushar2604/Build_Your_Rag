"""Planner — turn a hiring goal into an ordered execution plan.

Deterministic and side-effect-free: it produces an `ExecutionPlan` describing
the steps that *would* run, and never invokes a tool. The step catalog is
configurable (pass a custom list) and modular (each step is an independent
template), mirroring the ranking engine's factor design.

    Planner().plan("Hire a Backend Intern")
    -> Read JD -> Search Candidates -> Rank -> Schedule -> Send Emails
       -> Collect Feedback -> Generate Shortlist -> Notify HR
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.hiring_agent.types.plan import ExecutionPlan, PlanStep


@dataclass(frozen=True)
class PlanStepTemplate:
    key: str
    name: str
    tool: str | None
    description: str  # may contain a `{role}` placeholder


# The default hiring plan. Each step names the tool that would execute it; the
# terminal "Notify HR" step has no tool yet (a future capability).
_DEFAULT_HIRING_PLAN: list[PlanStepTemplate] = [
    PlanStepTemplate(
        "read_jd", "Read JD", "read_job",
        "Parse the {role} job description and extract required skills, "
        "experience, responsibilities, and interview stages.",
    ),
    PlanStepTemplate(
        "search_candidates", "Search Candidates", "search_candidates",
        "Semantically search the candidate knowledge base for matches to the "
        "job context.",
    ),
    PlanStepTemplate(
        "rank", "Rank", "rank_candidates",
        "Score and order candidates by skill match, experience, education, "
        "projects, and interview history.",
    ),
    PlanStepTemplate(
        "schedule", "Schedule", "schedule_interview",
        "Book interviews between the top candidates and recruiters.",
    ),
    PlanStepTemplate(
        "send_emails", "Send Emails", "send_email",
        "Send interview invitations to the scheduled candidates.",
    ),
    PlanStepTemplate(
        "collect_feedback", "Collect Feedback", "collect_feedback",
        "Aggregate interviewer feedback and verdicts.",
    ),
    PlanStepTemplate(
        "generate_shortlist", "Generate Shortlist", "generate_shortlist",
        "Compile the final shortlist from scores and feedback.",
    ),
    PlanStepTemplate(
        "notify_hr", "Notify HR", None,
        "Notify HR with the final shortlist and hiring summary.",
    ),
]

# Seniority keywords recognized in a goal, most specific first.
_SENIORITY = [
    "intern", "junior", "entry-level", "entry level", "associate",
    "mid-level", "mid level", "senior", "staff", "principal", "lead",
]
# Leading words stripped when deriving the role phrase from a goal.
_STOPWORDS = {
    "hire", "recruit", "find", "get", "onboard", "a", "an", "the", "for",
    "our", "we", "need", "to", "some", "new",
}


class Planner:
    """Builds an ExecutionPlan from a goal. Configurable via a custom catalog."""

    def __init__(self, catalog: list[PlanStepTemplate] | None = None) -> None:
        self._catalog = catalog if catalog is not None else _DEFAULT_HIRING_PLAN

    def plan(self, goal: str) -> ExecutionPlan:
        role, seniority = self._parse_goal(goal)
        role_label = role or "the role"

        steps: list[PlanStep] = []
        for i, tmpl in enumerate(self._catalog):
            steps.append(
                PlanStep(
                    id=i,
                    key=tmpl.key,
                    name=tmpl.name,
                    tool=tmpl.tool,
                    description=tmpl.description.format(role=role_label),
                    depends_on=[i - 1] if i > 0 else [],
                )
            )

        summary = " -> ".join(s.name for s in steps)
        return ExecutionPlan(
            goal=goal, role=role, seniority=seniority, steps=steps, summary=summary
        )

    @staticmethod
    def _parse_goal(goal: str) -> tuple[str, str]:
        """Extract (role, seniority) from a free-form goal."""
        text = goal.strip()
        lower = text.lower()
        seniority = next((s for s in _SENIORITY if s in lower), "")

        tokens = re.split(r"\s+", text)
        kept = [t for t in tokens if t.lower().strip(",.") not in _STOPWORDS]
        role = " ".join(kept).strip() or text
        return role, seniority
