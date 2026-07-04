"""Hiring Agent — Job Context types.

The structured result of ingesting a job description: the searchable
document metadata plus the extracted hiring criteria the downstream
workflow (search → rank → schedule) reasons over.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobContext(BaseModel):
    """Structured hiring criteria extracted from a job description."""

    title: str = ""
    required_skills: list[str] = Field(default_factory=list)
    experience: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    interview_stages: list[str] = Field(default_factory=list)


class ReadJobResult(BaseModel):
    """What ReadJobService returns: the ingested document handle + job context.

    `document_id` and `chunk_count` come from the reused chatbot ingestion
    pipeline (IngestDocument); the chunks are stored in the same pgvector
    corpus and are immediately searchable by the tenant.
    """

    document_id: str
    chunk_count: int
    status: str
    job_context: JobContext
    extraction_note: str | None = None
