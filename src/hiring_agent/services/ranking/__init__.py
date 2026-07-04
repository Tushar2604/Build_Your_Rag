"""Modular, configurable candidate-ranking engine.

    engine   — RankingEngine (weighted combination of factors)
    factors  — one pluggable scorer per dimension + default_factors()

Typical use:
    engine = RankingEngine(weights=RankingWeights(skill_match=0.5, ...))
    result = engine.rank(candidate_signals, job_context)

Customize by passing a different `factors` list and/or `weights`.
"""

from __future__ import annotations

from src.hiring_agent.services.ranking.engine import RankingEngine
from src.hiring_agent.services.ranking.factors import (
    EducationFactor,
    ExperienceFactor,
    FactorOutcome,
    InterviewHistoryFactor,
    ProjectsFactor,
    RankingFactor,
    SkillMatchFactor,
    default_factors,
)

__all__ = [
    "EducationFactor",
    "ExperienceFactor",
    "FactorOutcome",
    "InterviewHistoryFactor",
    "ProjectsFactor",
    "RankingEngine",
    "RankingFactor",
    "SkillMatchFactor",
    "default_factors",
]
