"""Evaluation harness for the RAG platform.

A self-contained package (sibling to `tests/`) that measures answer quality
programmatically so agent/prompt/retrieval changes can ship without regressions.

Three layers, each independently usable:

  * `metrics`     — pure, deterministic scoring functions (retrieval + grounding).
                    No network, no DB; fully unit-tested.
  * `judge`       — an LLM-as-judge for the subjective axes (faithfulness, answer
                    relevance) built on the existing `LLMProvider` port.
  * `runner`      — drives a golden dataset through an `EvalTarget` (the live RAG
                    pipeline or a fake), aggregates metrics into an `EvalReport`.
  * `regression`  — compares a report against a stored baseline and fails CI when
                    a tracked metric drops beyond its tolerance.

Run it:  `python -m evals.cli run --dataset evals/datasets/sample.jsonl`
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
