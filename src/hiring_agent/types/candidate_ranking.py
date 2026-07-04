"""Hiring Agent — candidate ranking types.

The inputs and outputs of the modular ranking engine:

    CandidateSignals  — everything a factor needs about one candidate
    RankingWeights    — the configurable per-factor weighting
    FactorScore       — one factor's contribution to a candidate's total
    RankedCandidate   — a candidate with its overall score + explanation
    RankingResult     — the ordered result set + the weights actually used
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Canonical factor names — the single source of truth shared by the weights
# model and the factor implementations.
FACTOR_SKILL_MATCH = "skill_match"
FACTOR_EXPERIENCE = "experience"
FACTOR_EDUCATION = "education"
FACTOR_PROJECTS = "projects"
FACTOR_INTERVIEW_HISTORY = "interview_history"


class CandidateSignals(BaseModel):
    """Normalized per-candidate inputs to the ranking engine.

    `matching_skills` / `missing_skills` / `similarity_score` come straight from
    the search step. The optional structured fields let a caller supply precise
    values (e.g. parsed years of experience); when absent, factors fall back to
    heuristics over `text` (the candidate's retrieved resume / interview text).
    """

    candidate_id: str
    similarity_score: float = 0.0
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    text: str = ""

    # Optional structured overrides (take precedence over text heuristics).
    years_experience: float | None = None
    education_level: str | None = None  # phd | master | bachelor | associate | none
    project_count: int | None = None
    interview_score: float | None = None  # prior interview signal in [0, 1]


class RankingWeights(BaseModel):
    """Configurable weighting of each ranking factor.

    Weights are relative — the engine normalizes them to sum to 1 so the overall
    score always lands in [0, 1] regardless of the raw values supplied. Set a
    weight to 0 to neutralize a factor without removing it.
    """

    skill_match: float = 0.40
    experience: float = 0.20
    education: float = 0.10
    projects: float = 0.15
    interview_history: float = 0.15

    def normalized(self) -> RankingWeights:
        values = {
            FACTOR_SKILL_MATCH: max(0.0, self.skill_match),
            FACTOR_EXPERIENCE: max(0.0, self.experience),
            FACTOR_EDUCATION: max(0.0, self.education),
            FACTOR_PROJECTS: max(0.0, self.projects),
            FACTOR_INTERVIEW_HISTORY: max(0.0, self.interview_history),
        }
        total = sum(values.values())
        if total <= 0:
            # Degenerate config → equal weighting across the five factors.
            equal = 1.0 / len(values)
            return RankingWeights(**dict.fromkeys(values, equal))
        return RankingWeights(**{k: v / total for k, v in values.items()})

    def for_factor(self, name: str) -> float:
        return float(getattr(self, name, 0.0))


class FactorScore(BaseModel):
    name: str
    raw_score: float  # the factor's own 0..1 assessment
    weight: float  # normalized weight applied
    contribution: float  # raw_score * weight
    detail: str  # human-readable justification


class RankedCandidate(BaseModel):
    candidate_id: str
    rank: int = 0
    overall_score: float = 0.0
    factor_scores: list[FactorScore] = Field(default_factory=list)
    explanation: str = ""
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class RankingResult(BaseModel):
    weights_used: RankingWeights
    total: int
    ranked: list[RankedCandidate] = Field(default_factory=list)
