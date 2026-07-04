"""SearchCandidatesTool — semantic search of the candidate knowledge base.

Runs IN-PROCESS (like ReadJobTool, and for the same reason: tenant-scoped
vector search cannot safely route through the static-API-key stdio MCP
subprocess). Reuses the platform's existing vector search via DocumentSearchTool
— no retrieval code is duplicated here.

Inputs (via kwargs):
    job_context : dict  — a JobContext (as produced by ReadJobTool), OR
    required_skills / preferred_skills / title / experience / responsibilities
                          — individual JobContext fields
    top_n               : int, default 20
    exclude_document_ids: list[str] — documents to omit (e.g. the job's own file)
When no job context is supplied (e.g. the workflow simulation passing only a
`job_id`), the tool returns a benign no-op so the workflow still advances.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec

log = structlog.get_logger(__name__)


class SearchCandidatesTool:
    spec = ToolSpec(
        name="search_candidates",
        description=(
            "Semantically search the candidate knowledge base (resume and "
            "interview-note embeddings) for the best matches to a JobContext. "
            "Returns the top matches, each with a similarity score, matching "
            "skills, missing skills, and reasoning."
        ),
        parameters={
            "job_context": {
                "type": "object",
                "description": "A JobContext object (as produced by read_job).",
            },
            "top_n": {
                "type": "integer",
                "description": "Maximum candidate matches to return (default 20).",
            },
            "exclude_document_ids": {
                "type": "array",
                "description": "Document ids to exclude (e.g. the job description itself).",
            },
        },
    )

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        job_context = self._resolve_job_context(kwargs)
        if job_context is None:
            return ToolResult(
                observation=(
                    "No job context supplied. Pass `job_context` (from read_job) "
                    "or job fields (required_skills, title, ...) to search candidates."
                ),
                data={"skipped": True},
                ok=True,
            )

        top_n = int(kwargs.get("top_n", 20))
        exclude = kwargs.get("exclude_document_ids") or None

        # Lazily reach the composition root and reuse the existing retrieval tool.
        from src.config.container import get_container
        from src.hiring_agent.services.search_candidates_service import (
            SearchCandidatesService,
        )
        from src.infrastructure.agent.document_search_tool import DocumentSearchTool

        container = get_container()
        search_tool = DocumentSearchTool(
            uow_factory=container.unit_of_work,
            embedder=container.embedder,
            default_top_k=container.settings.retrieval_top_k,
        )
        service = SearchCandidatesService(search_tool)

        log.info(
            "hiring.tool.search_candidates.invoke",
            tenant=str(ctx.tenant_id),
            required_skills=len(job_context.required_skills),
            top_n=top_n,
        )

        try:
            result = await service.execute(
                ctx, job_context, top_n=top_n, exclude_document_ids=exclude
            )
        except Exception as exc:  # noqa: BLE001 - surface as a handled tool error
            log.error(
                "hiring.tool.search_candidates.failed",
                tenant=str(ctx.tenant_id),
                error=str(exc),
            )
            return ToolResult(
                observation=f"[search_candidates error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )

        preview = "; ".join(
            f"{m.candidate_id[:8]} (score {m.similarity_score}, "
            f"{len(m.matching_skills)} skills, {len(m.missing_skills)} gaps)"
            for m in result.matches[:5]
        )
        observation = (
            f"Found {result.total_matches} candidate match(es). "
            + (preview or "No candidates matched the job context.")
            + (" ..." if result.total_matches > 5 else "")
        )
        return ToolResult(observation=observation, data=result.model_dump(), ok=True)

    @staticmethod
    def _resolve_job_context(kwargs: dict[str, Any]):  # type: ignore[no-untyped-def]
        """Build a JobContext from a dict or from individual field kwargs."""
        from src.hiring_agent.types import JobContext

        raw = kwargs.get("job_context")
        if isinstance(raw, dict):
            fields = set(JobContext.model_fields)
            return JobContext(**{k: v for k, v in raw.items() if k in fields})

        field_kwargs = {
            "title": kwargs.get("title", ""),
            "required_skills": kwargs.get("required_skills") or [],
            "experience": kwargs.get("experience", ""),
            "responsibilities": kwargs.get("responsibilities") or [],
            "preferred_skills": kwargs.get("preferred_skills") or [],
        }
        if not any(field_kwargs.values()):
            return None
        return JobContext(**field_kwargs)
