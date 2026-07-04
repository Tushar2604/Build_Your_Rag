"""Deterministic tests for the eval metrics — no network, no DB.

These pin the numbers the regression gate trusts. If a metric's definition
changes, a test here must change with it — that is the point.
"""

from __future__ import annotations

import math

from evals.metrics import (
    RetrievalScores,
    citation_grounding,
    hit_at_k,
    mean,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    refusal_correct,
)


def test_hit_at_k_found_and_missed() -> None:
    assert hit_at_k(["a", "b", "c"], ["c"], k=3) == 1.0
    assert hit_at_k(["a", "b", "c"], ["z"], k=3) == 0.0
    # Relevant doc is outside the top-k window.
    assert hit_at_k(["a", "b", "c"], ["c"], k=2) == 0.0


def test_recall_and_precision() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["a", "c", "z"]  # z never retrieved
    assert recall_at_k(retrieved, relevant, k=4) == 2 / 3
    assert precision_at_k(retrieved, relevant, k=4) == 2 / 4


def test_reciprocal_rank_uses_first_relevant_rank() -> None:
    assert reciprocal_rank(["x", "y", "a"], ["a"]) == 1 / 3
    assert reciprocal_rank(["a", "y", "z"], ["a"]) == 1.0
    assert reciprocal_rank(["x", "y"], ["a"]) == 0.0


def test_ndcg_is_one_when_relevant_ranked_first() -> None:
    assert ndcg_at_k(["a", "b"], ["a"], k=2) == 1.0


def test_ndcg_discounts_lower_ranks() -> None:
    # One relevant doc at rank 3: dcg = 1/log2(4); idcg = 1/log2(2) = 1.
    score = ndcg_at_k(["x", "y", "a"], ["a"], k=3)
    assert math.isclose(score, 1.0 / math.log2(4))


def test_duplicate_documents_collapse_to_best_rank() -> None:
    # Same doc retrieved twice (multiple chunks) — counts once, at its first rank.
    assert reciprocal_rank(["a", "a", "b"], ["a"]) == 1.0
    assert precision_at_k(["a", "a"], ["a"], k=2) == 1.0


def test_no_relevant_set_yields_zero_retrieval_metrics() -> None:
    assert hit_at_k(["a"], [], k=3) == 0.0
    assert recall_at_k(["a"], [], k=3) == 0.0
    assert ndcg_at_k(["a"], [], k=3) == 0.0


def test_citation_grounding_rewards_correct_abstention() -> None:
    # Retrieved nothing for an out-of-scope question -> perfect grounding.
    assert citation_grounding([], []) == 1.0
    # Retrieved something when nothing was relevant -> zero.
    assert citation_grounding(["a"], []) == 0.0
    # Mixed precision.
    assert citation_grounding(["a", "b"], ["a"]) == 0.5


def test_refusal_correct() -> None:
    refusal = "I'm here to help with our open roles and your application."
    answer = "The refund window is 30 days."
    assert refusal_correct(refusal, expect_refusal=True) is True
    assert refusal_correct(answer, expect_refusal=False) is True
    assert refusal_correct(answer, expect_refusal=True) is False
    assert refusal_correct(refusal, expect_refusal=False) is False


def test_retrieval_scores_as_dict_keys_use_k() -> None:
    scores = RetrievalScores.compute(["a", "b"], ["a"], k=5)
    d = scores.as_dict()
    assert set(d) == {"hit@5", "recall@5", "precision@5", "mrr", "ndcg@5"}
    assert d["hit@5"] == 1.0


def test_mean_handles_empty() -> None:
    assert mean([]) == 0.0
    assert mean([0.0, 1.0]) == 0.5
