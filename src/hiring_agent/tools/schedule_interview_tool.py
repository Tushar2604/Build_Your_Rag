"""ScheduleInterviewTool — book an interview via a (mock) calendar backend.

Runs IN-PROCESS through the CalendarProvider port. Today the port resolves to
MockCalendarProvider (no external API); later `build_calendar_provider` will
return a GoogleCalendarProvider with no change to this tool.

Inputs (via kwargs):
    candidate       : str | dict  — candidate name, or {id, name, email}
    recruiter       : str | dict  — recruiter name, or {id, name, email}
    preferred_time  : str         — ISO 8601 start time (defaults to tomorrow 10:00 UTC)
    duration_minutes: int         — default 45
    title           : str         — optional meeting title
When neither candidate nor recruiter is supplied (e.g. the workflow simulation
passing only a `job_id`), the tool returns a benign no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from src.application.agent.tools import ToolContext, ToolResult, ToolSpec

log = structlog.get_logger(__name__)


class ScheduleInterviewTool:
    spec = ToolSpec(
        name="schedule_interview",
        description=(
            "Schedule an interview between a candidate and a recruiter at a "
            "preferred time via the calendar service (currently a mock backend). "
            "Returns the meeting object, a calendar link, and a booking status."
        ),
        parameters={
            "candidate": {
                "type": "string",
                "description": "Candidate name, or an object {id, name, email}.",
            },
            "recruiter": {
                "type": "string",
                "description": "Recruiter name, or an object {id, name, email}.",
            },
            "preferred_time": {
                "type": "string",
                "description": "ISO 8601 start time (default: tomorrow 10:00 UTC).",
            },
            "duration_minutes": {
                "type": "integer",
                "description": "Meeting length in minutes (default 45).",
            },
            "title": {
                "type": "string",
                "description": "Optional meeting title.",
            },
        },
    )

    async def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        candidate_raw = kwargs.get("candidate")
        recruiter_raw = kwargs.get("recruiter")
        if not candidate_raw and not recruiter_raw:
            return ToolResult(
                observation=(
                    "No candidate/recruiter supplied. Pass `candidate` and "
                    "`recruiter` (and optionally `preferred_time`) to schedule."
                ),
                data={"skipped": True},
                ok=True,
            )

        from src.hiring_agent.services.calendar import build_calendar_provider
        from src.hiring_agent.services.schedule_interview_service import (
            ScheduleInterviewService,
        )
        from src.hiring_agent.types import MeetingRequest

        request = MeetingRequest(
            candidate=self._party(candidate_raw),
            recruiter=self._party(recruiter_raw),
            start_time=self._parse_time(kwargs.get("preferred_time")),
            duration_minutes=int(kwargs.get("duration_minutes", 45)),
            title=str(kwargs.get("title", "")),
        )

        log.info(
            "hiring.tool.schedule_interview.invoke",
            tenant=str(ctx.tenant_id),
            candidate=request.candidate.name or request.candidate.id,
            recruiter=request.recruiter.name or request.recruiter.id,
            start=request.start_time.isoformat(),
        )

        try:
            provider = build_calendar_provider()
            service = ScheduleInterviewService(provider)
            result = await service.execute(request)
        except Exception as exc:  # noqa: BLE001 - surface as a handled tool error
            log.error("hiring.tool.schedule_interview.failed", error=str(exc))
            return ToolResult(
                observation=f"[schedule_interview error] {type(exc).__name__}: {exc}",
                data={"error": str(exc), "error_type": type(exc).__name__},
                ok=False,
            )

        m = result.meeting
        observation = (
            f"Interview '{m.title}' {m.status} for "
            f"{m.start_time.isoformat()} ({m.provider} calendar). "
            f"Meeting {m.meeting_id}. Calendar link: {result.calendar_link}"
        )
        return ToolResult(
            observation=observation,
            data=result.model_dump(mode="json"),
            ok=True,
        )

    # ------------------------------------------------------------------
    # Input coercion
    # ------------------------------------------------------------------

    @staticmethod
    def _party(raw: Any):  # type: ignore[no-untyped-def]
        from src.hiring_agent.types import Party

        if isinstance(raw, dict):
            fields = set(Party.model_fields)
            return Party(**{k: v for k, v in raw.items() if k in fields})
        if isinstance(raw, str) and raw.strip():
            value = raw.strip()
            # Treat an '@' as an email; otherwise a display name.
            return Party(email=value) if "@" in value else Party(name=value)
        return Party()

    @staticmethod
    def _parse_time(raw: Any) -> datetime:
        """Parse an ISO 8601 start time; default to tomorrow at 10:00 UTC."""
        default = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        if not raw or not isinstance(raw, str):
            return default
        try:
            # Python 3.11 fromisoformat handles 'Z' and offsets.
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return default
