"""Shared helpers between `ScheduleInterview` (one candidate, admin-supplied
email) and the bulk `InterviewBatch` use cases (many candidates, same job
description, email extracted from the resume) — question generation and the
candidate invite email are identical in both paths, so they live here once.
"""

from __future__ import annotations

import re

from src.application.ports.services import LLMProvider
from src.domain.interview.entities import Interview
from src.domain.interview.prompts import build_interview_turn_prompt

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value.strip()))


async def generate_interview_questions(llm: LLMProvider, job_text: str, resume_text: str) -> list[str]:
    prompt = build_interview_turn_prompt(
        job_text=job_text,
        resume_text=resume_text,
        instruction=(
            "Generate 5 to 7 structured interview questions that probe the "
            "candidate's fit for this specific role, referencing specifics "
            "from their resume where relevant. Reply with ONLY the "
            "questions, one per line, no numbering, no extra commentary."
        ),
    )
    result = await llm.generate(
        "You are an expert interview question designer for technical and behavioral hiring.",
        prompt,
    )
    lines = [line.strip(" -\t*") for line in result.text.splitlines() if line.strip()]
    return lines[:8] or ["Tell me about your relevant experience for this role."]


# Below this many admin-supplied questions, top up with LLM-generated ones so
# a short custom list still becomes a real interview. At/above it, the
# admin's questions are used exactly as given — no surprise extra ones.
_MIN_QUESTIONS_BEFORE_TOPUP = 4


async def build_question_set(
    llm: LLMProvider, job_text: str, resume_text: str, custom_questions: list[str] | None
) -> list[str]:
    """The admin's questions are always asked, always first. The LLM only
    fills in more if the admin gave too few for a real interview."""
    custom = [q.strip() for q in (custom_questions or []) if q.strip()]
    if len(custom) >= _MIN_QUESTIONS_BEFORE_TOPUP:
        return custom
    generated = await generate_interview_questions(llm, job_text, resume_text)
    return custom + generated


async def extract_candidate_identity(llm: LLMProvider, resume_text: str) -> tuple[str, str]:
    """Best-effort name + email extraction from resume text — used only by
    the bulk batch path, where there's no admin typing in one specific
    candidate's email. A malformed or missing email comes back blank so the
    review table surfaces it rather than silently guessing wrong."""
    if not resume_text.strip():
        return "", ""
    result = await llm.generate(
        "Extract the candidate's full name and email address from this resume. "
        "Reply with EXACTLY two lines and nothing else:\nName: <full name>\n"
        "Email: <email address, or blank if none found>",
        resume_text[:4000],
    )
    name, email = "", ""
    for line in result.text.splitlines():
        low = line.strip().lower()
        if low.startswith("name:"):
            name = line.split(":", 1)[1].strip(' "\'')[:200]
        elif low.startswith("email:"):
            email = line.split(":", 1)[1].strip(' "\'')[:320]
    if not looks_like_email(email):
        email = ""
    return name, email


def build_invite_html(interview: Interview, join_url: str) -> str:
    greeting = f"Hi {interview.candidate_name}," if interview.candidate_name else "Hi,"
    role = interview.role_title or "the role"
    if interview.window_closes_at is not None:
        when = (
            f"any time between <strong>{interview.scheduled_at.strftime('%B %d, %Y')}</strong> "
            f"and <strong>{interview.window_closes_at.strftime('%B %d, %Y')}</strong>"
        )
    else:
        when = f"on <strong>{interview.scheduled_at.strftime('%B %d, %Y at %H:%M UTC')}</strong>"
    return (
        f"<p>{greeting}</p>"
        f"<p>You're invited to interview for <strong>{role}</strong> — join {when}.</p>"
        f"<p>When you're ready, start here: <a href=\"{join_url}\">{join_url}</a></p>"
        f"<p>The interview is conducted by an AI interviewer over voice — just "
        f"open the link and follow the prompts. No account needed.</p>"
    )
