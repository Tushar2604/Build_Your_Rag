"""CollectFeedbackTool — aggregates interviewer feedback via MCP."""

from __future__ import annotations

from src.application.agent.tools import ToolSpec
from src.hiring_agent.tools._base import BaseMCPTool


class CollectFeedbackTool(BaseMCPTool):
    spec = ToolSpec(
        name="collect_feedback",
        description=(
            "Aggregate post-interview feedback from all interviewers for a job. "
            "Returns per-candidate verdicts, scores, and notes. "
            "Verdicts: strong_hire | hire | maybe | no_hire | no_show."
        ),
        parameters={
            "job_id": {
                "type": "string",
                "description": "Job whose interview feedback to collect.",
            },
        },
    )
