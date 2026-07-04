"""SearchCandidatesService — semantic candidate search over the shared corpus.

Reuses the platform's existing vector search WITHOUT reimplementing any
retrieval logic: it delegates embedding + pgvector search to the very same
`DocumentSearchTool` the chatbot agent uses (embed the query, run a
tenant-scoped `chunks.search`, return citations). This service only composes
on top of those citations:

    1. Build a search query from the JobContext.
    2. Delegate retrieval to DocumentSearchTool  (reused; no duplicate code).
    3. Aggregate the returned chunk citations into candidate-level matches
       (one per source document — a resume or interview-note file).
    4. For each candidate: similarity score, matching skills, missing skills,
       and a short reasoning string.

Resumes and interview notes are ingested through the same pipeline as any
document (see ReadJobService / IngestDocument), so they are already embedded
and searchable in the tenant's corpus — nothing new to index here.
"""

from __future__ import annotations

import structlog

from src.application.agent.tools import Tool, ToolContext
from src.hiring_agent.types import CandidateMatch, JobContext, SearchCandidatesResult

log = structlog.get_logger(__name__)

# Retrieve well beyond the final candidate count: a single candidate may own
# several matching chunks, so we over-fetch chunks and then collapse to distinct
# candidate documents before taking the top N.
_DEFAULT_RETRIEVE_CHUNKS = 100


class SearchCandidatesService:
    def __init__(self, search_tool: Tool) -> None:
        # `search_tool` is a DocumentSearchTool (the reused retrieval primitive).
        # Typed as the Tool protocol so it stays trivially fakeable in tests.
        self._search = search_tool

    async def execute(
        self,
        ctx: ToolContext,
        job_context: JobContext,
        *,
        top_n: int = 20,
        retrieve_chunks: int = _DEFAULT_RETRIEVE_CHUNKS,
        exclude_document_ids: list[str] | None = None,
    ) -> SearchCandidatesResult:
        query = self._build_query(job_context)

        # --- REUSE: delegate all retrieval to the existing vector search tool ---
        result = await self._search.run(ctx, query=query, top_k=retrieve_chunks)
        citations = result.data.get("citations", []) if result.ok else []

        exclude = set(exclude_document_ids or [])
        candidates = self._aggregate_by_candidate(citations, exclude)

        # Rank by best semantic similarity — "top N semantic matches".
        ranked = sorted(
            candidates.items(), key=lambda kv: kv[1]["score"], reverse=True
        )[:top_n]

        required = job_context.required_skills
        preferred = job_context.preferred_skills
        matches = [
            self._to_match(doc_id, agg, required, preferred)
            for doc_id, agg in ranked
        ]

        log.info(
            "search_candidates.done",
            tenant=str(ctx.tenant_id),
            retrieved_chunks=len(citations),
            candidates=len(matches),
        )
        return SearchCandidatesResult(
            query=query, total_matches=len(matches), matches=matches
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_query(jc: JobContext) -> str:
        """Compose a natural-language retrieval query from the job context."""
        parts: list[str] = []
        if jc.title:
            parts.append(jc.title)
        if jc.required_skills:
            parts.append("Required skills: " + ", ".join(jc.required_skills))
        if jc.experience:
            parts.append("Experience: " + jc.experience)
        if jc.responsibilities:
            parts.append("Responsibilities: " + "; ".join(jc.responsibilities))
        if jc.preferred_skills:
            parts.append("Preferred skills: " + ", ".join(jc.preferred_skills))
        return ". ".join(parts) or "candidate"

    @staticmethod
    def _aggregate_by_candidate(
        citations: list[dict], exclude: set[str]
    ) -> dict[str, dict]:
        """Collapse chunk-level citations into one entry per source document."""
        by_doc: dict[str, dict] = {}
        for c in citations:
            doc_id = str(c.get("document_id", ""))
            if not doc_id or doc_id in exclude:
                continue
            score = float(c.get("score", 0.0))
            snippet = str(c.get("snippet", ""))
            entry = by_doc.setdefault(
                doc_id,
                {"score": 0.0, "passages": 0, "texts": [], "best_snippet": ""},
            )
            entry["passages"] += 1
            entry["texts"].append(snippet)
            if score > entry["score"]:
                entry["score"] = score
                entry["best_snippet"] = snippet
        return by_doc

    @classmethod
    def _to_match(
        cls,
        doc_id: str,
        agg: dict,
        required: list[str],
        preferred: list[str],
    ) -> CandidateMatch:
        haystack = " ".join(agg["texts"]).lower()
        matching = [s for s in (required + preferred) if s.lower() in haystack]
        missing = [s for s in required if s.lower() not in haystack]
        return CandidateMatch(
            candidate_id=doc_id,
            similarity_score=round(agg["score"], 4),
            matched_passages=agg["passages"],
            matching_skills=matching,
            missing_skills=missing,
            reasoning=cls._reason(required, matching, missing, agg["score"], agg["passages"]),
            snippet=agg["best_snippet"][:300],
        )

    @staticmethod
    def _reason(
        required: list[str],
        matching: list[str],
        missing: list[str],
        score: float,
        passages: int,
    ) -> str:
        matched_req = [s for s in required if s in matching]
        text = f"{len(matched_req)}/{len(required)} required skills present"
        if matched_req:
            text += f" ({', '.join(matched_req)})"
        text += "."
        text += (
            f" Missing: {', '.join(missing)}."
            if missing
            else " No required-skill gaps."
        )
        return text + f" Best similarity {score:.3f} across {passages} passage(s)."
