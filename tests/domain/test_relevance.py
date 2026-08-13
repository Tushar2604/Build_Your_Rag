"""Unit tests for retrieval pruning.

The bug these protect against is not a crash — it is an assistant that answers
fluently from the wrong paragraph. `top_k` fills its quota regardless of score,
so a question the knowledge base cannot answer still reaches the model as
"reference material", and the model dutifully uses it.
"""

from __future__ import annotations

from src.domain.chat.entities import Citation
from src.domain.chat.relevance import RELATIVE_FLOOR, prune_citations
from src.domain.shared.identifiers import DocumentId, new_id


def _cite(score: float, ordinal: int = 0) -> Citation:
    return Citation(
        document_id=DocumentId(new_id()),
        chunk_id=f"chunk-{ordinal}",
        ordinal=ordinal,
        score=score,
        snippet=f"snippet {ordinal}",
    )


def test_nothing_retrieved_stays_nothing() -> None:
    assert prune_citations([], min_score=0.15) == []


def test_the_absolute_floor_drops_obvious_noise() -> None:
    kept = prune_citations([_cite(0.7, 1), _cite(0.05, 2)], min_score=0.15)
    assert [c.ordinal for c in kept] == [1]


def test_everything_below_the_floor_yields_no_context() -> None:
    # Better an empty context — where the prompt switches to its strict
    # "you have no sources" wording — than five irrelevant chunks presented as
    # the source of truth.
    assert prune_citations([_cite(0.04), _cite(0.02)], min_score=0.15) == []


def test_filler_far_below_the_best_hit_is_dropped() -> None:
    # The common shape: one real match, plus whatever else was needed to fill
    # top_k. The tail is what the model ends up quoting from.
    hits = [_cite(0.80, 1), _cite(0.76, 2), _cite(0.30, 3), _cite(0.22, 4)]
    kept = prune_citations(hits, min_score=0.15)
    assert [c.ordinal for c in kept] == [1, 2]


def test_the_relative_cut_can_never_empty_a_surviving_result() -> None:
    # The top hit always scores 100% of itself, so a uniformly weak-but-passing
    # result set is kept rather than thrown away.
    hits = [_cite(0.18, 1), _cite(0.17, 2)]
    assert len(prune_citations(hits, min_score=0.15)) == 2


def test_a_uniformly_strong_result_set_survives_intact() -> None:
    hits = [_cite(0.9, 1), _cite(0.88, 2), _cite(0.85, 3)]
    assert len(prune_citations(hits, min_score=0.15)) == 3


def test_ranking_order_is_preserved() -> None:
    hits = [_cite(0.9, 1), _cite(0.7, 2), _cite(0.6, 3)]
    assert [c.ordinal for c in prune_citations(hits, min_score=0.0)] == [1, 2, 3]


def test_the_relative_floor_is_measured_against_the_best_survivor() -> None:
    # Not against the best of the *raw* hits: a strong chunk excluded by the
    # absolute floor is impossible, but a caller passing a stricter min_score
    # must still get a cut relative to what actually remains.
    hits = [_cite(0.9, 1), _cite(0.5, 2), _cite(0.4, 3)]
    kept = prune_citations(hits, min_score=0.45)
    assert [c.ordinal for c in kept] == [1]
    # 0.5 was above min_score but is below 0.9 * RELATIVE_FLOOR.
    assert 0.5 < 0.9 * RELATIVE_FLOOR
