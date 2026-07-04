"""Calendar provider port.

The single seam between the scheduling service and any calendar backend. The
mock adapter satisfies it today; a GoogleCalendarProvider will satisfy the same
protocol later — the service and tool never change.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.hiring_agent.types.interview import Meeting, MeetingRequest


@runtime_checkable
class CalendarProvider(Protocol):
    name: str

    async def create_event(self, request: MeetingRequest) -> Meeting:
        """Create a calendar event and return the resulting Meeting."""
        ...
