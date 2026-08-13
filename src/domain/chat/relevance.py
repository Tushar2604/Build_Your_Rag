"""Deciding which retrieved chunks are actually worth showing the model.

`top_k` is a *budget*, not a relevance test: the vector search returns its k
best chunks whatever their scores, so a question the knowledge base cannot
answer still arrives at the model as k paragraphs presented under the heading
"reference material". The model does what it is asked and answers from them —
which is what "it replies from a different context even though I gave it a
knowledge base" looks like from the outside.

Two filters, applied together, because each catches a case the other misses:

  * An absolute floor drops chunks that resemble the question so little that
    they cannot be about it. Deliberately low. An earlier attempt at 0.65 (see
    the note in `RagGraph._assemble`) emptied the context for almost every
    query, because cosine scores from `gemini-embedding-001` rarely reach it —
    and an empty context is its own failure mode. The floor exists to cut
    obvious noise, not to adjudicate relevance.

  * A relative floor drops chunks that are much weaker than the best hit. This
    is the one that fixes the common case: one genuinely relevant chunk plus
    four fillers dragged in to reach `top_k`. It is scale-free, so it keeps
    working if the embedding model changes and its score distribution moves.
    It can never empty a non-empty result — the top hit always scores 100% of
    itself.
"""

from __future__ import annotations

from src.domain.chat.entities import Citation

# A chunk scoring below this share of the best hit is treated as filler.
# 0.6 is loose enough to keep genuine supporting passages (which cluster close
# to the top hit) and tight enough to drop the unrelated tail.
RELATIVE_FLOOR = 0.6


def prune_citations(
    citations: list[Citation], *, min_score: float, relative_floor: float = RELATIVE_FLOOR
) -> list[Citation]:
    """Keep the citations that are plausibly about the question.

    Order is preserved, so the caller's ranking survives. Re-ordinals nothing:
    the ordinal identifies the source chunk, not its position in this list.
    """
    if not citations:
        return []
    kept = [c for c in citations if c.score >= min_score]
    if not kept:
        return []
    cutoff = max(c.score for c in kept) * relative_floor
    return [c for c in kept if c.score >= cutoff]
