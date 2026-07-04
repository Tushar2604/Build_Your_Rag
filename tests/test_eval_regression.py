"""Tests for the regression gate and the offline runner.

The runner is exercised with a fake `EvalTarget` (no DB / no LLM), proving the
whole dataset→metrics→report→gate path runs deterministically in CI.
"""

from __future__ import annotations

import pytest
from evals.dataset import EvalCase, GoldenDataset
from evals.regression import evaluate_regressions
from evals.report import EvalReport
from evals.runner import EvalRunner
from evals.target import TargetOutput


class _ScriptedTarget:
    """Returns a canned `TargetOutput` per question text."""

    def __init__(self, by_question: dict[str, TargetOutput]) -> None:
        self._by_question = by_question

    async def answer(self, question: str) -> TargetOutput:
        return self._by_question[question]


def _dataset() -> GoldenDataset:
    return GoldenDataset(
        name="unit",
        cases=[
            EvalCase(id="q1", question="where?", relevant_doc_ids=["a"]),
            EvalCase(id="q2", question="scope?", expect_refusal=True),
        ],
    )


@pytest.mark.asyncio
async def test_runner_scores_retrieval_and_refusal() -> None:
    target = _ScriptedTarget(
        {
            "where?": TargetOutput(answer="It's in doc a.", retrieved_doc_ids=["a", "b"]),
            "scope?": TargetOutput(
                answer="I'm here to help with our open roles and your application.",
                retrieved_doc_ids=[],
            ),
        }
    )
    report = await EvalRunner(target, k=5).run(_dataset(), target_name="fake")

    assert report.num_cases == 2
    # q1 retrieved the relevant doc at rank 1.
    assert report.aggregate["hit@5"] == 1.0
    assert report.aggregate["mrr"] == 1.0
    # Both cases handled the refusal policy correctly.
    assert report.aggregate["refusal_correct"] == 1.0


@pytest.mark.asyncio
async def test_runner_flags_wrong_refusal() -> None:
    target = _ScriptedTarget(
        {
            "where?": TargetOutput(answer="doc a", retrieved_doc_ids=["a"]),
            # Should have refused but answered instead.
            "scope?": TargetOutput(answer="Sure, the weather is sunny.", retrieved_doc_ids=[]),
        }
    )
    report = await EvalRunner(target, k=5).run(_dataset(), target_name="fake")
    assert report.aggregate["refusal_correct"] == 0.5


def _report(**aggregate: float) -> EvalReport:
    return EvalReport(dataset="d", num_cases=1, aggregate=dict(aggregate))


def test_regression_detected_beyond_tolerance() -> None:
    baseline = _report(**{"hit@5": 1.0, "faithfulness": 0.9})
    current = _report(**{"hit@5": 0.8, "faithfulness": 0.85})  # hit drops past tol 0.0
    verdict = evaluate_regressions(baseline, current)
    assert not verdict.passed
    regressed = {d.metric for d in verdict.regressions}
    assert "hit@5" in regressed
    # faithfulness drop (0.05) is within its 0.10 tolerance -> not a regression.
    assert "faithfulness" not in regressed


def test_no_regression_within_tolerance() -> None:
    baseline = _report(**{"ndcg@5": 0.80})
    current = _report(**{"ndcg@5": 0.77})  # drop 0.03 < tol 0.05
    assert evaluate_regressions(baseline, current).passed


def test_improvement_is_not_a_regression() -> None:
    baseline = _report(**{"mrr": 0.5})
    current = _report(**{"mrr": 0.9})
    verdict = evaluate_regressions(baseline, current)
    assert verdict.passed
    assert verdict.deltas[0].delta > 0


def test_new_metric_is_ignored_not_failed() -> None:
    baseline = _report(**{"hit@5": 1.0})
    current = _report(**{"hit@5": 1.0, "answer_relevance": 0.4})
    verdict = evaluate_regressions(baseline, current)
    assert verdict.passed
    assert "answer_relevance" in verdict.missing_metrics
