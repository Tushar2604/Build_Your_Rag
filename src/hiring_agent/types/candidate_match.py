"""Hiring Agent — candidate-match types.

The structured result of semantically searching the candidate knowledge base
(resume + interview-note chunks) against a JobContext.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateMatch(BaseModel):
    """One candidate surfaced by semantic search, with a skills gap analysis.

    `candidate_id` is the id of the candidate's source document (resume /
    interview notes) in the shared corpus — the same document id the ingestion
    pipeline assigns.
    """

    candidate_id: str
    similarity_score: float
    matched_passages: int
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    reasoning: str = ""
    snippet: str = ""


class SearchCandidatesResult(BaseModel):
    query: str
    total_matches: int
    matches: list[CandidateMatch] = Field(default_factory=list)
