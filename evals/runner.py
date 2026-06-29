"""Drives a golden dataset through a target and aggregates the scores.

For each case: ask the target, compute the deterministic retrieval + grounding
metrics, and (optionally) call the LLM judge for faithfulness/relevance. Per-case
rows roll up into an `EvalReport` whose aggregate is the mean of every metric.

The judge is optional (`judge=None`) so the harness runs fully offline in unit
tests and CI smoke runs, then layers the subjective axes on when an LLM is wired.
"""

from __future__ import annotations

import structlog

from evals.dataset import GoldenDataset
from evals.judge import LLMJudge
from evals.metrics import RetrievalScores, citation_grounding, mean, refusal_correct
from evals.report import CaseResult, EvalReport
from evals.target import EvalTarget

log = structlog.get_logger(__name__)


class EvalRunner:
    def __init__(self, target: EvalTarget, *, k: int = 5, judge: LLMJudge | None = None) -> None:
        self._target = target
        self._k = k
        self._judge = judge

    async def run(self, dataset: GoldenDataset, *, target_name: str = "unknown") -> EvalReport:
        results: list[CaseResult] = []
        for case in dataset:
            out = await self._target.answer(case.question)

            metrics: dict[str, float] = {}
            judge_ok = True

            # Retrieval metrics only mean something when the case is labelled with
            # a relevant set; adversarial/refusal cases skip them.
            if case.relevant_doc_ids:
                scores = RetrievalScores.compute(
                    out.retrieved_doc_ids, case.relevant_doc_ids, self._k
                )
                metrics.update(scores.as_dict())
                metrics["citation_grounding"] = citation_grounding(
                    out.retrieved_doc_ids, case.relevant_doc_ids
                )

            # Deterministic policy check applies to every case.
            metrics["refusal_correct"] = float(
                refusal_correct(out.answer, expect_refusal=case.expect_refusal)
            )

            # Subjective axes — only when a judge is wired and the case expects a
            # real (non-refusal) answer.
            if self._judge is not None and not case.expect_refusal:
                faith = await self._judge.faithfulness(out.context, out.answer)
                rel = await self._judge.answer_relevance(case.question, out.answer)
                judge_ok = faith.ok and rel.ok
                if faith.ok:
                    metrics["faithfulness"] = faith.score
                if rel.ok:
                    metrics["answer_relevance"] = rel.score

            results.append(
                CaseResult(
                    case_id=case.id,
                    question=case.question,
                    metrics=metrics,
                    answer=out.answer,
                    tags=case.tags,
                    judge_ok=judge_ok,
                )
            )
            log.info("eval.case", case_id=case.id, metrics=metrics)

        return EvalReport(
            dataset=dataset.name,
            target=target_name,
            num_cases=len(results),
            aggregate=_aggregate(results),
            cases=results,
        )


def _aggregate(results: list[CaseResult]) -> dict[str, float]:
    """Mean of each metric across the cases that reported it.

    Metrics are averaged only over cases where they apply (e.g. retrieval metrics
    skip refusal cases), so a sparse metric isn't dragged down by absent rows.
    """
    keys: set[str] = set()
    for r in results:
        keys.update(r.metrics)
    return {
        key: mean([r.metrics[key] for r in results if key in r.metrics]) for key in sorted(keys)
    }
