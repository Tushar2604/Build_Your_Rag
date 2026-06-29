"""Pure scoring functions — the deterministic backbone of the harness.

Everything here is a pure function of (ground truth, system output): no network,
no DB, no LLM. That keeps the numbers reproducible and lets the whole module run
in milliseconds in CI. The subjective axes (faithfulness, answer relevance) live
in `judge.py` because they need an LLM; these do not.

Retrieval metrics treat retrieval as ranked information retrieval and operate on
the *document ids* a query retrieved versus the labelled relevant set:

  * hit@k        — did any relevant doc appear in the top-k?  (0/1)
  * recall@k     — fraction of relevant docs found in the top-k
  * precision@k  — fraction of the top-k that are relevant
  * mrr          — reciprocal rank of the first relevant doc (rank sensitive)
  * ndcg@k       — rank-weighted gain, normalised to [0, 1]

Grounding metrics are deterministic answer checks that don't need a judge:

  * refusal_correct — did the bot refuse exactly when it should have?
  * citation_grounding — share of retrieved docs that were labelled relevant
    (a cheap precision proxy that needs no answer text).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


def _dedupe_preserve_order(ids: Sequence[str]) -> list[str]:
    """Collapse a ranked id list to first-occurrence order.

    A query can retrieve several chunks from the same document; for document-level
    retrieval metrics only the best (first) rank of each document counts.
    """
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def hit_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """1.0 if any relevant id is in the top-k, else 0.0."""
    if not relevant:
        return 0.0
    top = _dedupe_preserve_order(retrieved)[:k]
    return 1.0 if any(r in top for r in relevant) else 0.0


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the relevant set that appears in the top-k."""
    if not relevant:
        return 0.0
    top = set(_dedupe_preserve_order(retrieved)[:k])
    found = sum(1 for r in set(relevant) if r in top)
    return found / len(set(relevant))


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the top-k that are relevant. Denominator is min(k, retrieved)."""
    top = _dedupe_preserve_order(retrieved)[:k]
    if not top:
        return 0.0
    rel = set(relevant)
    return sum(1 for r in top if r in rel) / len(top)


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    """1 / rank of the first relevant id (1-indexed); 0 if none retrieved."""
    rel = set(relevant)
    for rank, doc_id in enumerate(_dedupe_preserve_order(retrieved), start=1):
        if doc_id in rel:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Normalised discounted cumulative gain with binary relevance.

    DCG sums 1/log2(rank+1) over relevant hits in the top-k; the ideal DCG
    assumes every relevant doc ranked first. Result is in [0, 1].
    """
    if not relevant:
        return 0.0
    rel = set(relevant)
    top = _dedupe_preserve_order(retrieved)[:k]
    dcg = sum(1.0 / math.log2(rank + 1) for rank, d in enumerate(top, start=1) if d in rel)
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


# --- Deterministic generation / grounding checks ---------------------------------

# Mirrors AskChatbot._REFUSAL_PREFIX: the canonical refusal opener. Kept in sync
# with the default system prompt so the harness recognises an in-policy refusal.
REFUSAL_PREFIX = "I can only answer questions about"


def is_refusal(answer: str) -> bool:
    """Heuristic: did the model emit the canonical out-of-scope refusal?"""
    return answer.strip().startswith(REFUSAL_PREFIX)


def refusal_correct(answer: str, *, expect_refusal: bool) -> bool:
    """Did the bot refuse exactly when it should have (and not otherwise)?"""
    return is_refusal(answer) == expect_refusal


def citation_grounding(retrieved_doc_ids: Sequence[str], relevant: Sequence[str]) -> float:
    """Precision proxy needing no answer text: of the distinct docs the bot
    actually pulled in, what share were labelled relevant? 1.0 when nothing was
    retrieved for a question that has no relevant set (correct abstention)."""
    retrieved = _dedupe_preserve_order(retrieved_doc_ids)
    if not retrieved:
        return 1.0 if not relevant else 0.0
    rel = set(relevant)
    return sum(1 for d in retrieved if d in rel) / len(retrieved)


@dataclass(frozen=True)
class RetrievalScores:
    hit_at_k: float
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    k: int

    @classmethod
    def compute(
        cls, retrieved: Sequence[str], relevant: Sequence[str], k: int
    ) -> RetrievalScores:
        return cls(
            hit_at_k=hit_at_k(retrieved, relevant, k),
            recall_at_k=recall_at_k(retrieved, relevant, k),
            precision_at_k=precision_at_k(retrieved, relevant, k),
            mrr=reciprocal_rank(retrieved, relevant),
            ndcg_at_k=ndcg_at_k(retrieved, relevant, k),
            k=k,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            f"hit@{self.k}": self.hit_at_k,
            f"recall@{self.k}": self.recall_at_k,
            f"precision@{self.k}": self.precision_at_k,
            "mrr": self.mrr,
            f"ndcg@{self.k}": self.ndcg_at_k,
        }


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean; 0.0 for an empty sequence (so aggregates never divide by
    zero on an empty slice)."""
    return sum(values) / len(values) if values else 0.0
