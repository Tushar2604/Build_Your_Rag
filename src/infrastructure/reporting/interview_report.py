"""Interview report PDF — the artifact a human (or a later AI pass) reviews.

Pure function: takes the finalized Interview and returns PDF bytes, stored by
the caller via the ObjectStorage port. fpdf2 is pure Python (no system deps),
so this needs no extra runtime setup beyond the pip install.
"""

from __future__ import annotations

from fpdf import FPDF

from src.domain.interview.entities import Interview

_VERDICT_LABELS = {
    "strong_hire": "Strong Hire",
    "hire": "Hire",
    "maybe": "Maybe",
    "no_hire": "No Hire",
}

# fpdf2's core fonts (Helvetica/Times/Courier) only support Latin-1, but LLM
# output routinely contains smart quotes, em-dashes, ellipses, etc. Normalize
# the common ones to ASCII, then replace anything still unencodable rather
# than crash report generation over a stray character.
_UNICODE_TO_ASCII = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "·": "-",
}


def _safe(text: str) -> str:
    for uni, ascii_ in _UNICODE_TO_ASCII.items():
        text = text.replace(uni, ascii_)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_interview_report_pdf(interview: Interview) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Interview Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _safe(f"Candidate: {interview.candidate_name or 'Unknown'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, _safe(f"Role: {interview.role_title or 'N/A'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 7,
        _safe(f"Interview date: {interview.scheduled_at.strftime('%Y-%m-%d %H:%M UTC')}"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    verdict_label = _VERDICT_LABELS.get(interview.overall_verdict or "", interview.overall_verdict or "Not scored")
    score_label = f"{interview.overall_score:.1f}/5" if interview.overall_score is not None else "N/A"
    pdf.cell(0, 9, _safe(f"Overall: {verdict_label}  -  Score: {score_label}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Question-by-question", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    for i, qs in enumerate(interview.scores, start=1):
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, _safe(f"Q{i}. {qs.question}  ({qs.score}/5)"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if qs.answer:
            pdf.set_text_color(60, 60, 60)
            pdf.multi_cell(0, 5.5, _safe(f"Answer: {qs.answer}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        if qs.justification:
            pdf.set_font("Helvetica", "I", 10)
            pdf.multi_cell(0, 5.5, _safe(f"Notes: {qs.justification}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    return bytes(pdf.output())
