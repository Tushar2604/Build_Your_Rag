"""MockCalendarProvider — an in-memory stand-in for a real calendar backend.

No external API calls. It fabricates a plausible meeting: a stable event id, a
calendar link, a join URL, and a status derived from the requested time (a slot
in the past can't be confirmed, so it comes back 'tentative'). This is the
adapter a GoogleCalendarProvider will replace.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.hiring_agent.types.interview import Meeting, MeetingRequest

# Where the fake links point. Not real hosts — purely illustrative so downstream
# code and logs have a URL-shaped value to carry.
_CALENDAR_BASE = "https://calendar.mock.local/event"
_MEET_BASE = "https://meet.mock.local"


class MockCalendarProvider:
    name = "mock"

    async def create_event(self, request: MeetingRequest) -> Meeting:
        meeting_id = f"mock-{uuid4().hex[:12]}"
        end_time = request.start_time + timedelta(minutes=request.duration_minutes)

        title = request.title or (
            f"Interview: {self._label(request.candidate)}"
            f" with {self._label(request.recruiter)}"
        )

        # A slot already in the past can't be firmly booked in a mock world.
        now = datetime.now(UTC)
        start = request.start_time
        is_future = start.tzinfo is not None and start > now or (
            start.tzinfo is None and start > now.replace(tzinfo=None)
        )
        status = "confirmed" if is_future else "tentative"

        return Meeting(
            meeting_id=meeting_id,
            title=title,
            candidate=request.candidate,
            recruiter=request.recruiter,
            start_time=start,
            end_time=end_time,
            calendar_link=f"{_CALENDAR_BASE}/{meeting_id}",
            join_url=f"{_MEET_BASE}/{meeting_id}",
            status=status,
            provider=self.name,
        )

    @staticmethod
    def _label(party) -> str:  # type: ignore[no-untyped-def]
        return party.name or party.email or party.id or "unknown"
