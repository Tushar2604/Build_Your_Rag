"""Model routing: send easy turns to a cheap model, escalate hard ones.

A real cost lever in the "agents platform": most turns are simple and don't need
the strongest model. The router picks a tier per turn from a cheap heuristic
(length, multi-hop / reasoning markers, prior step count). It returns an
`LLMProvider`, so the loop stays provider-agnostic and the heuristic can later be
swapped for a learned classifier without touching the loop.

When only one provider is supplied (the common free-tier case) routing is a
no-op that still records the chosen tier in the trace — the seam exists for when
a second tier is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.application.ports.services import LLMProvider

# Lexical markers that a question needs multi-step / comparative reasoning.
_HARD_MARKERS = re.compile(
    r"\b(compare|versus|vs\.?|why|explain|trade-?off|difference|each|across|"
    r"step by step|reason|analyze|analyse|summari[sz]e all|how many)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteDecision:
    tier: str  # "cheap" | "strong"
    provider: LLMProvider
    reason: str


class ModelRouter:
    def __init__(self, cheap: LLMProvider, strong: LLMProvider | None = None) -> None:
        self._cheap = cheap
        self._strong = strong or cheap

    def route(self, question: str, *, step_index: int = 0) -> RouteDecision:
        long_question = len(question) > 300
        hard = bool(_HARD_MARKERS.search(question))
        # Later steps in a run mean the agent is still working a hard problem;
        # escalate so it doesn't stall on a weak model.
        deep = step_index >= 2

        if (hard or long_question or deep) and self._strong is not self._cheap:
            reason = "long" if long_question else ("multi-step" if deep else "reasoning markers")
            return RouteDecision("strong", self._strong, reason)
        return RouteDecision("cheap", self._cheap, "default cheap tier")
