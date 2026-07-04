"""Calendar backends for interview scheduling.

    base — CalendarProvider port
    mock — MockCalendarProvider (current, no external API)

`build_calendar_provider()` is the single swap point. Today it always returns
the mock. When Google Calendar lands, add a GoogleCalendarProvider (satisfying
CalendarProvider) and select it here based on settings — nothing else changes.
"""

from __future__ import annotations

from src.hiring_agent.services.calendar.base import CalendarProvider
from src.hiring_agent.services.calendar.mock import MockCalendarProvider


def build_calendar_provider(settings: object | None = None) -> CalendarProvider:
    """Return the active calendar provider.

    `settings` is accepted (and currently unused) so the future Google swap is a
    one-line change here, e.g.:
        if getattr(settings, "google_calendar_enabled", False):
            return GoogleCalendarProvider(settings)
    """
    return MockCalendarProvider()


__all__ = [
    "CalendarProvider",
    "MockCalendarProvider",
    "build_calendar_provider",
]
