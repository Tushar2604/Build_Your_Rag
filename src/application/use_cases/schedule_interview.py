"""ScheduleInterview — the admin-triggered orchestration for a Virtual
Interview: validate the JD/resume documents, extract the candidate's name (if
not given), generate the fixed question set, persist the Interview, then
best-effort create a Google Calendar event and email the candidate — both
skipped gracefully (not treated as failures) when unconfigured. Neither
integration blocks scheduling; the admin UI reports what actually happened.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from src.application.ports.repositories import UnitOfWork
from src.application.ports.services import LLMProvider
from src.application.use_cases._interview_shared import build_invite_html, build_question_set
from src.domain.document.entities import IngestionStatus
from src.domain.interview.entities import Interview
from src.domain.shared.errors import InvalidStateError, NotFoundError
from src.domain.shared.identifiers import DocumentId, TenantId
from src.infrastructure.calendar.google import GoogleCalendarClient
from src.infrastructure.email.resend import ResendEmailSender

log = structlog.get_logger(__name__)


class ScheduleInterview:
    def __init__(
        self,
        uow: UnitOfWork,
        llm: LLMProvider,
        calendar: GoogleCalendarClient,
        email: ResendEmailSender,
        frontend_base_url: str,
    ) -> None:
        self._uow = uow
        self._llm = llm
        self._calendar = calendar
        self._email = email
        self._frontend_base = frontend_base_url.rstrip("/")

    async def execute(
        self,
        tenant_id: TenantId,
        *,
        candidate_name: str,
        candidate_email: str,
        role_title: str,
        job_document_id: DocumentId,
        resume_document_id: DocumentId,
        scheduled_at: datetime,
        custom_questions: list[str] | None = None,
    ) -> tuple[Interview, bool, bool]:
        """Returns (interview, calendar_created, email_sent)."""
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            job_text = await self._full_text(uow, tenant_id, job_document_id)
            resume_text = await self._full_text(uow, tenant_id, resume_document_id)

        name = candidate_name.strip() or await self._extract_name(resume_text)
        questions = await build_question_set(self._llm, job_text, resume_text, custom_questions)

        interview = Interview(
            tenant_id=tenant_id,
            candidate_name=name,
            candidate_email=candidate_email,
            role_title=role_title,
            job_document_id=job_document_id,
            resume_document_id=resume_document_id,
            scheduled_at=scheduled_at,
            questions=questions,
        )

        calendar_created = await self._try_create_calendar_event(tenant_id, interview)

        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            await uow.interviews.add(interview)
            await uow.commit()

        join_url = f"{self._frontend_base}/interview/{interview.access_token}"
        email_sent = await self._try_send_invite(interview, join_url)

        return interview, calendar_created, email_sent

    async def _try_create_calendar_event(self, tenant_id: TenantId, interview: Interview) -> bool:
        if not self._calendar.enabled:
            return False
        async with self._uow as uow:
            uow.set_tenant_scope(tenant_id)
            connection = await uow.google_connections.get(tenant_id)
            if connection is None:
                return False
            try:
                connection = await self._calendar.ensure_fresh(connection)
                event_id, html_link = await self._calendar.create_event(
                    connection,
                    summary=f"Interview: {interview.candidate_name or 'Candidate'}"
                    f"{' — ' + interview.role_title if interview.role_title else ''}",
                    description="Automated interview scheduled via the platform. "
                    "The candidate will receive a link to join.",
                    start_time=interview.scheduled_at,
                    duration_minutes=30,
                    attendee_email=interview.candidate_email,
                )
            except Exception:  # noqa: BLE001 - calendar is best-effort, never blocks scheduling
                log.warning("interview.calendar_create_failed", tenant_id=str(tenant_id))
                return False
            interview.google_event_id = event_id
            interview.calendar_link = html_link
            await uow.google_connections.upsert(connection)  # persist any refreshed token
            await uow.commit()
        return True

    async def _try_send_invite(self, interview: Interview, join_url: str) -> bool:
        if not self._email.enabled:
            return False
        try:
            return await self._email.send(
                to=interview.candidate_email,
                subject=f"Your interview for {interview.role_title or 'the role'} is scheduled",
                html=build_invite_html(interview, join_url),
            )
        except Exception:  # noqa: BLE001 - email is best-effort
            log.warning("interview.email_send_failed", tenant_id=str(interview.tenant_id))
            return False

    async def _full_text(self, uow: UnitOfWork, tenant_id: TenantId, document_id: DocumentId) -> str:
        doc = await uow.documents.get(tenant_id, document_id)
        if doc is None:
            raise NotFoundError(f"Document {document_id} not found.")
        if doc.status != IngestionStatus.READY:
            raise InvalidStateError(
                f"Document {document_id} is not ready yet (status={doc.status})."
            )
        chunks = await uow.chunks.list_for_document(tenant_id, document_id)
        return "\n\n".join(c.text for c in chunks)

    async def _extract_name(self, resume_text: str) -> str:
        if not resume_text.strip():
            return ""
        result = await self._llm.generate(
            "Extract the candidate's full name from this resume. Reply with "
            "ONLY the name and nothing else.",
            resume_text[:4000],
        )
        first_line = result.text.strip().splitlines()[0] if result.text.strip() else ""
        return first_line.strip(' "\'')[:200]

