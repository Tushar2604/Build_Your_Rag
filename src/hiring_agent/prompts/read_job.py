"""Prompts for extracting a structured Job Context from a job description."""

from __future__ import annotations

# Keep the extraction bounded — job descriptions rarely exceed a few pages, and
# a hard cap protects the token budget on very large inputs.
MAX_JOB_TEXT_CHARS = 12_000

READ_JOB_SYSTEM = (
    "You are a hiring analyst. Extract structured hiring criteria from a job "
    "description. Respond with ONLY a JSON object — no prose, no markdown code "
    "fences. Use exactly these keys:\n"
    '  "title": string (the role title, or "" if unclear)\n'
    '  "required_skills": array of strings (hard requirements / must-have skills)\n'
    '  "experience": string (a concise summary of the experience requirement, '
    'e.g. "5+ years backend engineering")\n'
    '  "responsibilities": array of strings (key day-to-day responsibilities)\n'
    '  "preferred_skills": array of strings (nice-to-have / bonus skills)\n'
    '  "interview_stages": array of strings (the interview process stages; if '
    "the description does not state them, infer a sensible standard sequence)\n"
    "Return empty arrays or empty strings for anything genuinely absent. "
    "Do not invent required skills that are not supported by the text."
)


def build_read_job_user_prompt(job_text: str) -> str:
    """Wrap the (untrusted) job description text for the extraction call.

    The text is delimited so the model treats it as data to analyse, not as
    instructions to follow — mirroring the platform's grounded-prompt pattern.
    """
    clipped = job_text[:MAX_JOB_TEXT_CHARS]
    return (
        "Extract the hiring criteria from the job description below and return "
        "the JSON object described in your instructions.\n\n"
        "<job_description>\n"
        f"{clipped}\n"
        "</job_description>"
    )
