"""FinalizeInterview — end-of-interview scoring + PDF report generation.

Triggered server-side once the candidate's answer to the last question is
processed (see interviews.py's /respond handler) — never left to the
candidate's browser, so it still runs even if they close the tab immediately
after the closing statement. One LLM call scores the whole transcript at once
(cheaper and more coherent than per-answer scoring); a malformed response
degrades to an unscored-but-still-completed interview rather than crashing —
a candidate's completed interview must never be lost over scoring JSON that
came back a little off.
"""

from __future__ import annotations

import json
import re

import structlog

from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import LLMProvider, ObjectStorage
from src.domain.interview.entities import Interview, QuestionScore
from src.domain.interview.prompts import build_scoring_prompt
from src.domain.shared.identifiers import TenantId
from src.infrastructure.reporting.interview_report import build_interview_report_pdf

log = structlog.get_logger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_VALID_VERDICTS = {"strong_hire", "hire", "maybe", "no_hire"}


class FinalizeInterview:
    def __init__(self, uow: UnitOfWork, llm: LLMProvider, storage: ObjectStorage) -> None:
        self._uow = uow
        self._llm = llm
        self._storage = storage

    async def execute(self, tenant_id: TenantId, interview: Interview) -> Interview:
        job_text, resume_text = await self._reference_texts(tenant_id, interview)
        transcript_text = "\n".join(f"{t.role.upper()}: {t.content}" for t in interview.transcript)

        scores, overall_score, overall_verdict = await self._score(
            job_text, resume_text, transcript_text
        )
        interview.scores = scores
        interview.overall_score = overall_score
        interview.overall_verdict = overall_verdict
        interview.status = "completed"

        try:
            pdf_bytes = build_interview_report_pdf(interview)
            key = f"interview-reports/{tenant_id}/{interview.id}.pdf"
            await self._storage.put_bytes(key, pdf_bytes, "application/pdf")
            interview.report_storage_key = key
        except Exception as exc:  # noqa: BLE001 - a failed PDF must not stop the interview from completing
            log.warning(
                "interview.pdf_generation_failed",
                interview_id=str(interview.id),
                error=f"{type(exc).__name__}: {exc}",
            )

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.interviews.update(interview)
            await uow.commit()

        return interview

    async def _reference_texts(self, tenant_id: TenantId, interview: Interview) -> tuple[str, str]:
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            job_chunks = await uow.chunks.list_for_document(tenant_id, interview.job_document_id)
            resume_chunks = await uow.chunks.list_for_document(tenant_id, interview.resume_document_id)
        return (
            "\n\n".join(c.text for c in job_chunks),
            "\n\n".join(c.text for c in resume_chunks),
        )

    async def _score(
        self, job_text: str, resume_text: str, transcript_text: str
    ) -> tuple[list[QuestionScore], float | None, str | None]:
        prompt = build_scoring_prompt(
            job_text=job_text, resume_text=resume_text, transcript_text=transcript_text
        )
        try:
            result = await self._llm.generate(
                "You are a fair, rigorous technical/behavioral interview evaluator.", prompt
            )
            match = _JSON_OBJECT.search(result.text)
            if not match:
                raise ValueError("no JSON object in scoring response")
            data = json.loads(match.group(0))

            scores = [
                QuestionScore(
                    question=str(q.get("question", ""))[:1000],
                    answer=str(q.get("answer", ""))[:4000],
                    score=max(1, min(5, int(q.get("score", 3)))),
                    justification=str(q.get("justification", ""))[:500],
                )
                for q in data.get("per_question", [])
                if isinstance(q, dict)
            ]
            raw_overall = data.get("overall_score")
            overall_score = float(raw_overall) if raw_overall is not None else None
            overall_verdict = data.get("overall_verdict")
            if overall_verdict not in _VALID_VERDICTS:
                overall_verdict = None
            return scores, overall_score, overall_verdict
        except Exception:  # noqa: BLE001 - never lose a completed interview over a scoring hiccup
            log.warning("interview.scoring_failed")
            return [], None, None
