"""Email template registry + renderer.

Each of the five hiring templates is a (subject, body) pair with `{placeholder}`
slots filled from a context dict. Rendering is tolerant: missing placeholders
resolve to an empty string (via `_SafeDict`) rather than raising, and a few
common fields have sensible defaults. All text is plain ASCII to stay safe in
logs and on any console.
"""

from __future__ import annotations

from src.hiring_agent.types.email import EmailTemplate

# Defaults applied under any caller-supplied context.
_DEFAULTS = {
    "candidate_name": "there",
    "company": "our company",
    "role": "the role",
    "recruiter_name": "the hiring team",
}

_TEMPLATES: dict[EmailTemplate, tuple[str, str]] = {
    EmailTemplate.INTERVIEW_INVITATION: (
        "Interview Invitation: {role} at {company}",
        "Hi {candidate_name},\n\n"
        "Thank you for applying for the {role} position at {company}. "
        "We would like to invite you to an interview.\n\n"
        "When: {interview_time}\n"
        "Join: {calendar_link}\n\n"
        "Please let us know if the time works for you.\n\n"
        "Best regards,\n{recruiter_name}",
    ),
    EmailTemplate.REMINDER: (
        "Reminder: Your {role} interview at {company}",
        "Hi {candidate_name},\n\n"
        "This is a friendly reminder about your upcoming interview for the "
        "{role} position at {company}.\n\n"
        "When: {interview_time}\n"
        "Join: {calendar_link}\n\n"
        "We look forward to speaking with you.\n\n"
        "Best regards,\n{recruiter_name}",
    ),
    EmailTemplate.REJECTION: (
        "Update on your {role} application",
        "Hi {candidate_name},\n\n"
        "Thank you for your interest in the {role} position at {company} and "
        "for the time you invested in the process. After careful "
        "consideration, we have decided not to move forward with your "
        "application at this time.\n\n"
        "We were impressed by your background and encourage you to apply for "
        "future openings that match your experience.\n\n"
        "We wish you the best in your search.\n\n"
        "Best regards,\n{recruiter_name}",
    ),
    EmailTemplate.SELECTION: (
        "You are moving forward: {role} at {company}",
        "Hi {candidate_name},\n\n"
        "Great news! You have been selected to move forward in the process for "
        "the {role} position at {company}.\n\n"
        "{next_steps}\n\n"
        "Congratulations, and we will be in touch shortly with the next steps.\n\n"
        "Best regards,\n{recruiter_name}",
    ),
    EmailTemplate.OFFER: (
        "Your offer for {role} at {company}",
        "Hi {candidate_name},\n\n"
        "We are delighted to offer you the {role} position at {company}.\n\n"
        "Compensation: {salary}\n"
        "Proposed start date: {start_date}\n\n"
        "Please review the attached details. We would be thrilled to have you "
        "join the team and are happy to answer any questions.\n\n"
        "Best regards,\n{recruiter_name}",
    ),
}


class _SafeDict(dict):
    """format_map helper: unknown placeholders render as empty strings."""

    def __missing__(self, key: str) -> str:  # noqa: D105
        return ""


def render(template: EmailTemplate, context: dict | None = None) -> tuple[str, str]:
    """Return (subject, body) for a template rendered with `context`."""
    merged = dict(_DEFAULTS)
    for key, value in (context or {}).items():
        if value is not None:
            merged[key] = str(value)
    subject_t, body_t = _TEMPLATES[template]
    data = _SafeDict(merged)
    return subject_t.format_map(data), body_t.format_map(data)


def available_templates() -> list[str]:
    return [t.value for t in EmailTemplate]
