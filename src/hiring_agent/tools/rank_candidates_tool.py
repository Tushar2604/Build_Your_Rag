"""RankCandidatesTool — order candidates with the modular ranking engine.

Pure compute (no DB, no tenant-scoped I/O): it feeds the search results into
the configurable `RankingEngine` and returns ordered candidates, each with an
overall score, per-factor breakdown, and a ranking explanation.

Inputs (via kwargs):
    candidates   : list[dict] — search results (CandidateMatch shape) and/or
                   explicit CandidateSignals fields per candidate
    job_context  : dict       — a JobContext (for skill/experience requirements)
    weights      : dict       — RankingWeights overrides (relative; normalized)
When no candidates are supplied (e.g. the workflow simulation passing only a
`job_id`), the tool returns a benign no-op so the workflow still advances.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec

log = structlog.get_logger(__name__)


class RankCandidatesTool:
    spec = ToolSpec(
        name="rank_candidates",
        description=(
            "Rank candidates using a modular, configurable scoring engine over "
            "five factors — skill match, experience, education, projects, and "
            "interview history. Returns ordered candidates with an overall score "
            "and a per-factor ranking explanation. Weights are configurable."
        ),
        parameters={
            "candidates": {
                "type": "array",
                "description": "Search results / candidate signals to rank.",
            },
            "job_context": {
                "type": "object",
                "description": "JobContext (required skills, experience, ...).",
            },
            "weights": {
                "type": "object",
                "description": (
                    "Optional factor weight overrides: skill_match, experience, "
                    "education, projects, interview_history (relative values)."
                ),
            },
        },
    )

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        raw_candidates = kwargs.get("candidates") or []
        if not raw_candidates:
            return ToolResult(
                observation=(
                    "No candidates supplied. Pass `candidates` (search results) "
                    "to rank them."
                ),
                data={"skipped": True},
                ok=True,
            )

        # Imported here to keep tool import light and mirror the other tools.
        from src.hiring_agent.services.ranking import RankingEngine
        from src.hiring_agent.types import JobContext, RankingWeights

        signals = [s for c in raw_candidates if (s := self._to_signals(c)) is not None]
        job = self._to_job_context(kwargs.get("job_context"), JobContext)
        weights = self._to_weights(kwargs.get("weights"), RankingWeights)

        log.info(
            "hiring.tool.rank_candidates.invoke",
            tenant=str(ctx.tenant_id),
            candidates=len(signals),
            custom_weights=weights is not None,
        )

        try:
            engine = RankingEngine(weights=weights)
            result = engine.rank(signals, job)
        except Exception as exc:  # noqa: BLE001 - surface as a handled tool error
            log.error("hiring.tool.rank_candidates.failed", error=str(exc))
            return ToolResult(
                observation=f"[rank_candidates error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )

        preview = "; ".join(
            f"#{c.rank} {c.candidate_id[:8]} ({c.overall_score})"
            for c in result.ranked[:5]
        )
        observation = (
            f"Ranked {result.total} candidate(s). "
            + (preview or "no rankable candidates.")
            + (" ..." if result.total > 5 else "")
        )
        return ToolResult(observation=observation, data=result.model_dump(), ok=True)

    # ------------------------------------------------------------------
    # Input coercion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_signals(raw: Any):  # type: ignore[no-untyped-def]
        """Build CandidateSignals from a flexible dict (CandidateMatch or signals)."""
        from src.hiring_agent.types.candidate_ranking import CandidateSignals

        if not isinstance(raw, dict):
            return None
        candidate_id = str(raw.get("candidate_id") or raw.get("id") or "")
        if not candidate_id:
            return None
        return CandidateSignals(
            candidate_id=candidate_id,
            similarity_score=float(raw.get("similarity_score", 0.0) or 0.0),
            matching_skills=raw.get("matching_skills") or [],
            missing_skills=raw.get("missing_skills") or [],
            text=str(raw.get("text") or raw.get("snippet") or ""),
            years_experience=raw.get("years_experience"),
            education_level=raw.get("education_level"),
            project_count=raw.get("project_count"),
            interview_score=raw.get("interview_score"),
        )

    @staticmethod
    def _to_job_context(raw: Any, job_cls):  # type: ignore[no-untyped-def]
        if isinstance(raw, dict):
            fields = set(job_cls.model_fields)
            return job_cls(**{k: v for k, v in raw.items() if k in fields})
        return job_cls()

    @staticmethod
    def _to_weights(raw: Any, weights_cls):  # type: ignore[no-untyped-def]
        if isinstance(raw, dict):
            fields = set(weights_cls.model_fields)
            return weights_cls(**{k: v for k, v in raw.items() if k in fields})
        return None
