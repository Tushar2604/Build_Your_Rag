"""Hiring Agent — interview scheduling types.

Field shapes deliberately mirror a Google Calendar event (event id, htmlLink,
status, start/end, conference link) so the eventual GoogleCalendarProvider maps
onto them without changing the tool or the service.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Party(BaseModel):
    """A meeting participant (candidate or recruiter)."""

    id: str = ""
    name: str = ""
    email: str = ""


class MeetingRequest(BaseModel):
    """Input to a calendar provider's `create_event`."""

    candidate: Party
    recruiter: Party
    start_time: datetime
    duration_minutes: int = 45
    title: str = ""
    description: str = ""


class Meeting(BaseModel):
    """A scheduled interview — the provider-agnostic 'meeting object'."""

    meeting_id: str
    title: str
    candidate: Party
    recruiter: Party
    start_time: datetime
    end_time: datetime
    calendar_link: str
    join_url: str = ""
    status: str  # confirmed | tentative | pending
    provider: str  # "mock" (later: "google")


class ScheduleInterviewResult(BaseModel):
    meeting: Meeting
    calendar_link: str
    status: str
    attendees: list[Party] = Field(default_factory=list)
