"""RankingEngine — combines pluggable factors under configurable weights.

The engine is deliberately dumb about *how* any single dimension is judged: it
asks each injected factor for a 0..1 score, multiplies by that factor's
normalized weight, sums the contributions into an overall score, then orders the
candidates. Swapping factors or reweighting them requires no change here — that
is the modular/configurable seam the task asks for.
"""

from __future__ import annotations

import structlog

from src.hiring_agent.services.ranking.factors import RankingFactor, default_factors
from src.hiring_agent.types.candidate_ranking import (
    CandidateSignals,
    FactorScore,
    RankedCandidate,
    RankingResult,
    RankingWeights,
)
from src.hiring_agent.types.job_context import JobContext

log = structlog.get_logger(__name__)


class RankingEngine:
    def __init__(
        self,
        factors: list[RankingFactor] | None = None,
        weights: RankingWeights | None = None,
    ) -> None:
        self._factors = factors if factors is not None else default_factors()
        self._weights = (weights or RankingWeights()).normalized()

    def rank(
        self, candidates: list[CandidateSignals], job: JobContext | None = None
    ) -> RankingResult:
        job = job or JobContext()
        ranked = [self._score_candidate(c, job) for c in candidates]

        # Highest overall first; ties broken by skill-search similarity, then id
        # for determinism.
        ranked.sort(key=lambda r: r.overall_score, reverse=True)
        for i, candidate in enumerate(ranked):
            candidate.rank = i + 1

        log.info("ranking.done", candidates=len(ranked), factors=len(self._factors))
        return RankingResult(
            weights_used=self._weights, total=len(ranked), ranked=ranked
        )

    def _score_candidate(
        self, signals: CandidateSignals, job: JobContext
    ) -> RankedCandidate:
        factor_scores: list[FactorScore] = []
        overall = 0.0
        for factor in self._factors:
            outcome = factor.score(signals, job)
            raw = max(0.0, min(1.0, outcome.score))
            weight = self._weights.for_factor(factor.name)
            contribution = raw * weight
            overall += contribution
            factor_scores.append(
                FactorScore(
                    name=factor.name,
                    raw_score=round(raw, 4),
                    weight=round(weight, 4),
                    contribution=round(contribution, 4),
                    detail=outcome.detail,
                )
            )

        return RankedCandidate(
            candidate_id=signals.candidate_id,
            overall_score=round(overall, 4),
            factor_scores=factor_scores,
            explanation=self._explain(overall, factor_scores),
            matching_skills=signals.matching_skills,
            missing_skills=signals.missing_skills,
        )

    @staticmethod
    def _explain(overall: float, factor_scores: list[FactorScore]) -> str:
        parts = [
            f"{fs.name} {fs.raw_score:.2f}×w{fs.weight:.2f}={fs.contribution:.3f} "
            f"({fs.detail})"
            for fs in factor_scores
        ]
        return f"Overall {overall:.3f}. " + "; ".join(parts) + "."
