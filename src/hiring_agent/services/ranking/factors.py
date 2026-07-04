"""Ranking factors — one pluggable scorer per ranking dimension.

Every factor implements the same tiny `RankingFactor` protocol: given a
candidate's signals and the job context, return a score in [0, 1] plus a
one-line justification. Factors are pure and synchronous, so they are trivial
to unit-test and to add/remove/reorder — that is what makes the ranking engine
modular. The engine handles weighting; a factor only judges its own dimension.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.hiring_agent.types.candidate_ranking import (
    FACTOR_EDUCATION,
    FACTOR_EXPERIENCE,
    FACTOR_INTERVIEW_HISTORY,
    FACTOR_PROJECTS,
    FACTOR_SKILL_MATCH,
    CandidateSignals,
)
from src.hiring_agent.types.job_context import JobContext


@dataclass(frozen=True)
class FactorOutcome:
    score: float  # clamped to [0, 1] by the engine
    detail: str


@runtime_checkable
class RankingFactor(Protocol):
    name: str

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome: ...


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class SkillMatchFactor:
    """Fraction of the job's required skills the candidate demonstrably has."""

    name = FACTOR_SKILL_MATCH

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome:
        required = job.required_skills
        if required:
            have = {s.lower() for s in signals.matching_skills}
            matched = [s for s in required if s.lower() in have]
            ratio = len(matched) / len(required)
            return FactorOutcome(
                _clamp(ratio),
                f"matched {len(matched)}/{len(required)} required skills",
            )
        # No required list available — fall back to the search-derived split.
        total = len(signals.matching_skills) + len(signals.missing_skills)
        if total == 0:
            return FactorOutcome(0.0, "no skill data available")
        ratio = len(signals.matching_skills) / total
        return FactorOutcome(
            _clamp(ratio),
            f"{len(signals.matching_skills)}/{total} skills present (no required list)",
        )


class ExperienceFactor:
    """Years of experience vs. the requirement parsed from the job context."""

    name = FACTOR_EXPERIENCE

    _YEARS_RE = re.compile(r"(\d+)\s*\+?\s*years?", re.IGNORECASE)

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome:
        years = signals.years_experience
        source = "provided"
        if years is None:
            years = self._parse_years(signals.text)
            source = "resume text"
        if years is None:
            return FactorOutcome(0.5, "no experience data (neutral)")

        required = self._parse_years(job.experience) or 5.0
        ratio = years / required if required else 0.0
        return FactorOutcome(
            _clamp(ratio),
            f"{years:g} yrs vs {required:g} required ({source})",
        )

    @classmethod
    def _parse_years(cls, text: str | None) -> float | None:
        if not text:
            return None
        matches = cls._YEARS_RE.findall(text)
        if not matches:
            return None
        return float(max(int(m) for m in matches))


class EducationFactor:
    """Highest education signal, mapped to a tier score."""

    name = FACTOR_EDUCATION

    _TIERS = {
        "phd": 1.0,
        "doctorate": 1.0,
        "master": 0.85,
        "bachelor": 0.70,
        "associate": 0.50,
        "none": 0.30,
    }
    # Ordered highest → lowest so text scanning picks the strongest signal.
    _TEXT_KEYS = [
        ("phd", ("phd", "ph.d", "doctorate")),
        ("master", ("master", "msc", "m.s", "mba")),
        ("bachelor", ("bachelor", "bsc", "b.s", "b.tech", "undergraduate")),
        ("associate", ("associate", "diploma")),
    ]

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome:
        if signals.education_level:
            key = signals.education_level.lower()
            return FactorOutcome(
                _clamp(self._TIERS.get(key, 0.3)), f"{key} (provided)"
            )
        haystack = signals.text.lower()
        for tier, keys in self._TEXT_KEYS:
            if any(k in haystack for k in keys):
                return FactorOutcome(self._TIERS[tier], f"{tier} (detected in text)")
        return FactorOutcome(0.4, "no education signal (neutral-low)")


class ProjectsFactor:
    """Project depth, from an explicit count or project-signal keywords."""

    name = FACTOR_PROJECTS

    _TARGET = 5  # count that saturates the score
    _KEYWORDS = ("project", "built", "shipped", "launched", "led ", "developed", "designed")

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome:
        count = signals.project_count
        source = "provided"
        if count is None:
            haystack = signals.text.lower()
            count = sum(haystack.count(k) for k in self._KEYWORDS)
            source = "keyword signals"
        if count <= 0:
            return FactorOutcome(0.3, "no project signals (neutral-low)")
        ratio = count / self._TARGET
        return FactorOutcome(_clamp(ratio), f"{count} project signal(s) ({source})")


class InterviewHistoryFactor:
    """Prior interview outcome, from an explicit score or verdict keywords."""

    name = FACTOR_INTERVIEW_HISTORY

    _VERDICTS = [
        (("strong hire", "strong_hire"), 1.0),
        (("hire", "positive", "advance"), 0.8),
        (("maybe", "neutral", "mixed"), 0.5),
        (("no hire", "no_hire", "reject", "no-show", "no_show"), 0.1),
    ]

    def score(self, signals: CandidateSignals, job: JobContext) -> FactorOutcome:
        if signals.interview_score is not None:
            return FactorOutcome(
                _clamp(signals.interview_score), "prior interview score (provided)"
            )
        haystack = signals.text.lower()
        for keys, value in self._VERDICTS:
            if any(k in haystack for k in keys):
                return FactorOutcome(value, f"verdict '{keys[0]}' (detected in text)")
        return FactorOutcome(0.5, "no interview history (neutral)")


def default_factors() -> list[RankingFactor]:
    """The standard five-factor set, in presentation order."""
    return [
        SkillMatchFactor(),
        ExperienceFactor(),
        EducationFactor(),
        ProjectsFactor(),
        InterviewHistoryFactor(),
    ]
