"""GenerateShortlistTool — compiles the final shortlist via MCP."""

from __future__ import annotations

from src.application.agent.tools import ToolSpec
from src.hiring_agent.tools._base import BaseMCPTool


class GenerateShortlistTool(BaseMCPTool):
    spec = ToolSpec(
        name="generate_shortlist",
        description=(
            "Compile the final hiring shortlist by combining fit scores, "
            "ranking results, and interviewer feedback verdicts. "
            "Returns the top-N candidates with structured rationale."
        ),
        parameters={
            "job_id": {
                "type": "string",
                "description": "Job to generate the shortlist for.",
            },
            "top_n": {
                "type": "integer",
                "description": "Maximum candidates on the shortlist (default 3).",
            },
        },
    )
