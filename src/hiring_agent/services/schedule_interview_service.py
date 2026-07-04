"""ScheduleInterviewService — book an interview through a calendar provider.

Provider-agnostic: it depends only on the CalendarProvider port, so swapping the
mock backend for Google Calendar requires no change here. The service owns the
orchestration (build the meeting object, surface link + status); the provider
owns the backend specifics.
"""

from __future__ import annotations

import structlog

from src.hiring_agent.services.calendar.base import CalendarProvider
from src.hiring_agent.types.interview import (
    MeetingRequest,
    ScheduleInterviewResult,
)

log = structlog.get_logger(__name__)


class ScheduleInterviewService:
    def __init__(self, calendar: CalendarProvider) -> None:
        self._calendar = calendar

    async def execute(self, request: MeetingRequest) -> ScheduleInterviewResult:
        meeting = await self._calendar.create_event(request)
        log.info(
            "schedule_interview.done",
            provider=meeting.provider,
            meeting_id=meeting.meeting_id,
            status=meeting.status,
        )
        return ScheduleInterviewResult(
            meeting=meeting,
            calendar_link=meeting.calendar_link,
            status=meeting.status,
            attendees=[request.candidate, request.recruiter],
        )
