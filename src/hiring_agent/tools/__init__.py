"""Hiring Agent — agent tools.

Concrete implementations of the application.agent.tools.Tool Protocol.
All tools return mock responses at this stage; no external I/O.

`build_hiring_registry()` composes the full tool set into the shared
ToolRegistry. `hiring_registry` is the module-level singleton used by
the WorkflowEngine.
"""

from __future__ import annotations

from src.application.agent.registry import ToolRegistry
from src.hiring_agent.tools._base import BaseMCPTool
from src.hiring_agent.tools.collect_feedback_tool import CollectFeedbackTool
from src.hiring_agent.tools.generate_shortlist_tool import GenerateShortlistTool
from src.hiring_agent.tools.rank_candidates_tool import RankCandidatesTool
from src.hiring_agent.tools.read_job_tool import ReadJobTool
from src.hiring_agent.tools.schedule_interview_tool import ScheduleInterviewTool
from src.hiring_agent.tools.search_candidates_tool import SearchCandidatesTool
from src.hiring_agent.tools.send_email_tool import SendEmailTool


def build_hiring_registry() -> ToolRegistry:
    """Construct a ToolRegistry populated with every hiring-agent tool."""
    return ToolRegistry(
        [
            ReadJobTool(),
            SearchCandidatesTool(),
            RankCandidatesTool(),
            ScheduleInterviewTool(),
            SendEmailTool(),
            CollectFeedbackTool(),
            GenerateShortlistTool(),
        ]
    )


# Module-level singleton — one registry per process, shared across requests.
hiring_registry = build_hiring_registry()

__all__ = [
    "BaseMCPTool",
    "CollectFeedbackTool",
    "GenerateShortlistTool",
    "RankCandidatesTool",
    "ReadJobTool",
    "ScheduleInterviewTool",
    "SearchCandidatesTool",
    "SendEmailTool",
    "build_hiring_registry",
    "hiring_registry",
]
