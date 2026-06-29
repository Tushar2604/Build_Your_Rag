"""Regression gate: compare a fresh report against a committed baseline.

This is what makes the harness a *gate* and not just a dashboard. A metric is a
regression when it drops below `baseline - tolerance`. Per-metric tolerances
absorb the inherent noise of LLM-judge scores (which wobble run to run) while
still catching real drops; deterministic retrieval metrics get a tight tolerance.

`evaluate_regressions` returns a structured verdict so the CLI can print a diff
and exit non-zero in CI — failing the build before a regression reaches users.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.report import EvalReport

# Metrics where higher is better and which gate the build. A metric absent here
# is reported but never fails CI (informational only).
DEFAULT_TOLERANCES: dict[str, float] = {
    "hit@5": 0.0,
    "recall@5": 0.05,
    "precision@5": 0.05,
    "mrr": 0.05,
    "ndcg@5": 0.05,
    "citation_grounding": 0.05,
    "refusal_correct": 0.0,  # a policy metric — no slack
    "faithfulness": 0.10,  # judge noise: wider band
    "answer_relevance": 0.10,
}


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    baseline: float
    current: float
    tolerance: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline

    @property
    def regressed(self) -> bool:
        # Drop beyond the tolerance band (small float epsilon to avoid jitter).
        return self.delta < -self.tolerance - 1e-9


@dataclass
class RegressionVerdict:
    deltas: list[MetricDelta] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)

    @property
    def regressions(self) -> list[MetricDelta]:
        return [d for d in self.deltas if d.regressed]

    @property
    def passed(self) -> bool:
        return not self.regressions

    def render(self) -> str:
        lines = []
        for d in sorted(self.deltas, key=lambda x: x.delta):
            flag = "FAIL" if d.regressed else ("up  " if d.delta > 1e-9 else "ok  ")
            lines.append(
                f"  [{flag}] {d.metric:<20} {d.baseline:6.3f} -> {d.current:6.3f} "
                f"({d.delta:+.3f}, tol {d.tolerance:.2f})"
            )
        if self.missing_metrics:
            lines.append(
                f"  (metrics not in baseline, ignored: {', '.join(self.missing_metrics)})"
            )
        verdict = (
            "PASS — no regressions"
            if self.passed
            else f"FAIL — {len(self.regressions)} regression(s)"
        )
        return "\n".join(lines) + f"\n{verdict}"


def evaluate_regressions(
    baseline: EvalReport,
    current: EvalReport,
    tolerances: dict[str, float] | None = None,
) -> RegressionVerdict:
    tol = tolerances or DEFAULT_TOLERANCES
    verdict = RegressionVerdict()
    for metric, current_value in sorted(current.aggregate.items()):
        if metric not in baseline.aggregate:
            verdict.missing_metrics.append(metric)
            continue
        verdict.deltas.append(
            MetricDelta(
                metric=metric,
                baseline=baseline.aggregate[metric],
                current=current_value,
                tolerance=tol.get(metric, 0.05),
            )
        )
    return verdict
