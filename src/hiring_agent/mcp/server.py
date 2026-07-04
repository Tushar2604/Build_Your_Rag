"""Hiring Agent MCP Server — exposes hiring capabilities as MCP tools.

This is the server side of the Hiring Agent's MCP integration.
The Hiring Agent client connects to this server (via stdio or any other
transport) and invokes these tools through the MCP protocol.

Run via stdio (for local dev / Claude Desktop):
    python -m src.hiring_agent.mcp.server

The existing RAG platform MCP server (src/interfaces/mcp/server.py) is
completely separate — this server is hiring-only and has no shared state.
"""

from __future__ import annotations


def build_server():  # type: ignore[no-untyped-def]
    """Construct the FastMCP server.  mcp SDK is imported here (deferred)
    so the module is importable without the optional mcp dependency."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("hiring-agent")

    # ------------------------------------------------------------------
    # Tool implementations — mock data only, no external I/O
    # ------------------------------------------------------------------

    @mcp.tool()
    async def read_job(job_id: str = "job-001") -> dict:
        """Retrieve and parse a job description by ID."""
        return {
            "observation": (
                f"Job '{job_id}' parsed successfully. "
                "Title: Senior Backend Engineer. "
                "Required skills: Python, FastAPI, PostgreSQL, Docker, Redis (5 total). "
                "Seniority: Senior (5+ years). Location: Remote. "
                "Salary band: $120k–$160k USD."
            ),
            "job_id": job_id,
            "title": "Senior Backend Engineer",
            "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
            "nice_to_have": ["Kubernetes", "LangChain", "Rust"],
            "experience_years_min": 5,
            "seniority": "Senior",
            "location": "Remote",
            "salary_band": {"min": 120_000, "max": 160_000, "currency": "USD"},
        }

    @mcp.tool()
    async def search_candidates(
        job_id: str = "job-001",
        top_k: int = 10,
        min_score: float = 0.60,
    ) -> dict:
        """Search the candidate pool for applicants matching a job."""
        all_candidates = [
            {"id": "c-001", "name": "Alice Hartman",   "score": 0.94, "skills_matched": 5},
            {"id": "c-002", "name": "Raj Patel",        "score": 0.91, "skills_matched": 5},
            {"id": "c-003", "name": "Sofia Mendes",     "score": 0.89, "skills_matched": 4},
            {"id": "c-004", "name": "James Okafor",     "score": 0.85, "skills_matched": 4},
            {"id": "c-005", "name": "Yuki Tanaka",      "score": 0.82, "skills_matched": 4},
            {"id": "c-006", "name": "Priya Nair",       "score": 0.79, "skills_matched": 3},
            {"id": "c-007", "name": "Luca Esposito",    "score": 0.76, "skills_matched": 3},
            {"id": "c-008", "name": "Amara Diallo",     "score": 0.74, "skills_matched": 3},
            {"id": "c-009", "name": "Chen Wei",         "score": 0.71, "skills_matched": 3},
            {"id": "c-010", "name": "Fatima Al-Rashid", "score": 0.68, "skills_matched": 3},
        ]
        results = [c for c in all_candidates if c["score"] >= min_score][:top_k]
        top = results[0] if results else None
        return {
            "observation": (
                f"Candidate search for job '{job_id}' complete. "
                f"47 candidates in pool; {len(results)} above score {min_score}. "
                + (f"Top match: {top['name']} (score {top['score']})." if top else "No results.")
            ),
            "job_id": job_id,
            "total_in_pool": 47,
            "above_threshold": len(results),
            "candidates": results,
        }

    @mcp.tool()
    async def rank_candidates(job_id: str = "job-001", top_n: int = 10) -> dict:
        """Score and rank candidates by composite fit (technical, experience, culture)."""
        ranked = [
            {"id": "c-001", "name": "Alice Hartman",   "fit_score": 0.94, "technical": 0.96, "experience": 0.92, "culture": 0.88},
            {"id": "c-002", "name": "Raj Patel",        "fit_score": 0.91, "technical": 0.93, "experience": 0.90, "culture": 0.86},
            {"id": "c-003", "name": "Sofia Mendes",     "fit_score": 0.89, "technical": 0.88, "experience": 0.91, "culture": 0.90},
            {"id": "c-004", "name": "James Okafor",     "fit_score": 0.85, "technical": 0.84, "experience": 0.87, "culture": 0.85},
            {"id": "c-005", "name": "Yuki Tanaka",      "fit_score": 0.82, "technical": 0.85, "experience": 0.80, "culture": 0.81},
            {"id": "c-006", "name": "Priya Nair",       "fit_score": 0.79, "technical": 0.81, "experience": 0.76, "culture": 0.80},
            {"id": "c-007", "name": "Luca Esposito",    "fit_score": 0.76, "technical": 0.74, "experience": 0.79, "culture": 0.75},
            {"id": "c-008", "name": "Amara Diallo",     "fit_score": 0.74, "technical": 0.72, "experience": 0.77, "culture": 0.74},
            {"id": "c-009", "name": "Chen Wei",         "fit_score": 0.71, "technical": 0.73, "experience": 0.70, "culture": 0.69},
            {"id": "c-010", "name": "Fatima Al-Rashid", "fit_score": 0.68, "technical": 0.66, "experience": 0.71, "culture": 0.68},
        ][:top_n]
        best = ranked[0]
        return {
            "observation": (
                f"Ranking complete for job '{job_id}'. Top {len(ranked)} candidates scored. "
                f"Fit scores: {ranked[-1]['fit_score']}–{best['fit_score']}. "
                f"Ranked #1: {best['name']} (technical {best['technical']}, "
                f"experience {best['experience']}, culture {best['culture']})."
            ),
            "job_id": job_id,
            "ranked_candidates": ranked,
            "score_range": {"min": ranked[-1]["fit_score"], "max": best["fit_score"]},
        }

    @mcp.tool()
    async def schedule_interview(job_id: str = "job-001", top_n: int = 10) -> dict:
        """Allocate interview time slots for top-ranked candidates."""
        all_slots = [
            {"candidate_id": "c-001", "name": "Alice Hartman",   "slot": "2026-07-10T09:00:00Z", "interviewer": "iv-001", "status": "confirmed"},
            {"candidate_id": "c-002", "name": "Raj Patel",        "slot": "2026-07-10T10:30:00Z", "interviewer": "iv-001", "status": "confirmed"},
            {"candidate_id": "c-003", "name": "Sofia Mendes",     "slot": "2026-07-10T13:00:00Z", "interviewer": "iv-002", "status": "confirmed"},
            {"candidate_id": "c-004", "name": "James Okafor",     "slot": "2026-07-11T09:00:00Z", "interviewer": "iv-002", "status": "confirmed"},
            {"candidate_id": "c-005", "name": "Yuki Tanaka",      "slot": "2026-07-11T10:30:00Z", "interviewer": "iv-003", "status": "confirmed"},
            {"candidate_id": "c-006", "name": "Priya Nair",       "slot": "2026-07-11T13:00:00Z", "interviewer": "iv-003", "status": "pending"},
            {"candidate_id": "c-007", "name": "Luca Esposito",    "slot": "2026-07-14T09:00:00Z", "interviewer": "iv-001", "status": "pending"},
            {"candidate_id": "c-008", "name": "Amara Diallo",     "slot": "2026-07-14T10:30:00Z", "interviewer": "iv-002", "status": "pending"},
            {"candidate_id": "c-009", "name": "Chen Wei",         "slot": "2026-07-14T13:00:00Z", "interviewer": "iv-003", "status": "pending"},
            {"candidate_id": "c-010", "name": "Fatima Al-Rashid", "slot": "2026-07-15T09:00:00Z", "interviewer": "iv-001", "status": "pending"},
        ][:top_n]
        confirmed = [s for s in all_slots if s["status"] == "confirmed"]
        return {
            "observation": (
                f"Interview scheduling for job '{job_id}' complete. "
                f"{len(all_slots)} slots across 3 interviewers. "
                f"{len(confirmed)} confirmed; {len(all_slots) - len(confirmed)} pending. "
                "2 slots reassigned due to interviewer conflicts."
            ),
            "job_id": job_id,
            "total_scheduled": len(all_slots),
            "confirmed": len(confirmed),
            "pending": len(all_slots) - len(confirmed),
            "conflicts_resolved": 2,
            "slots": all_slots,
        }

    @mcp.tool()
    async def send_email(template: str = "interview_invite", top_n: int = 10) -> dict:
        """Queue personalised emails to candidates using a named template."""
        _templates = {
            "interview_invite": "Personalised interview invitation with slot details and JD summary.",
            "rejection": "Respectful rejection with encouragement to apply for future roles.",
            "offer": "Offer letter with compensation details and start date.",
        }
        all_recipients = [
            {"candidate_id": "c-001", "name": "Alice Hartman",   "email": "alice@example.com",   "status": "queued"},
            {"candidate_id": "c-002", "name": "Raj Patel",        "email": "raj@example.com",     "status": "queued"},
            {"candidate_id": "c-003", "name": "Sofia Mendes",     "email": "sofia@example.com",   "status": "queued"},
            {"candidate_id": "c-004", "name": "James Okafor",     "email": "james@example.com",   "status": "queued"},
            {"candidate_id": "c-005", "name": "Yuki Tanaka",      "email": "yuki@example.com",    "status": "queued"},
            {"candidate_id": "c-006", "name": "Priya Nair",       "email": "priya@example.com",   "status": "queued"},
            {"candidate_id": "c-007", "name": "Luca Esposito",    "email": "luca@example.com",    "status": "queued"},
            {"candidate_id": "c-008", "name": "Amara Diallo",     "email": "amara@example.com",   "status": "queued"},
            {"candidate_id": "c-009", "name": "Chen Wei",         "email": "chen@example.com",    "status": "queued"},
            {"candidate_id": "c-010", "name": "Fatima Al-Rashid", "email": "fatima@example.com",  "status": "queued"},
        ][:top_n]
        return {
            "observation": (
                f"{len(all_recipients)} emails queued using template '{template}'. "
                f"Content: {_templates.get(template, 'Custom template.')} "
                "Delivery expected within 5 minutes."
            ),
            "template": template,
            "total_queued": len(all_recipients),
            "recipients": all_recipients,
        }

    @mcp.tool()
    async def collect_feedback(job_id: str = "job-001") -> dict:
        """Aggregate post-interview feedback from all interviewers."""
        feedback = [
            {"candidate_id": "c-001", "name": "Alice Hartman",   "verdict": "strong_hire", "technical": 5, "communication": 5, "notes": "Exceptional distributed systems depth."},
            {"candidate_id": "c-002", "name": "Raj Patel",        "verdict": "hire",        "technical": 4, "communication": 5, "notes": "Solid problem-solving; great communicator."},
            {"candidate_id": "c-003", "name": "Sofia Mendes",     "verdict": "hire",        "technical": 4, "communication": 4, "notes": "Strong FastAPI; excellent culture fit."},
            {"candidate_id": "c-004", "name": "James Okafor",     "verdict": "maybe",       "technical": 3, "communication": 4, "notes": "Good communication; needs infra growth."},
            {"candidate_id": "c-005", "name": "Yuki Tanaka",      "verdict": "maybe",       "technical": 4, "communication": 3, "notes": "Deep Python; reserved style."},
            {"candidate_id": "c-006", "name": "Priya Nair",       "verdict": "no_hire",     "technical": 3, "communication": 3, "notes": "Missed key DB design questions."},
            {"candidate_id": "c-007", "name": "Luca Esposito",    "verdict": "no_hire",     "technical": 2, "communication": 4, "notes": "Experience below requirements."},
            {"candidate_id": "c-008", "name": "Amara Diallo",     "verdict": "no_show",     "technical": 0, "communication": 0, "notes": "Did not attend."},
            {"candidate_id": "c-009", "name": "Chen Wei",         "verdict": "no_show",     "technical": 0, "communication": 0, "notes": "Did not attend."},
            {"candidate_id": "c-010", "name": "Fatima Al-Rashid", "verdict": "no_hire",     "technical": 3, "communication": 3, "notes": "Skills mismatch for this role."},
        ]
        responded = [f for f in feedback if f["verdict"] != "no_show"]
        hires = [f for f in responded if f["verdict"] in {"strong_hire", "hire"}]
        return {
            "observation": (
                f"Feedback collected for job '{job_id}'. "
                f"{len(responded)}/{len(feedback)} responded (72 h window simulated). "
                f"{len(feedback) - len(responded)} no-shows. "
                f"{len(hires)} positive hire verdicts: "
                + ", ".join(f["name"] for f in hires) + "."
            ),
            "job_id": job_id,
            "total_interviewed": len(feedback),
            "responded": len(responded),
            "no_shows": len(feedback) - len(responded),
            "verdicts": {
                "strong_hire": sum(1 for f in responded if f["verdict"] == "strong_hire"),
                "hire": sum(1 for f in responded if f["verdict"] == "hire"),
                "maybe": sum(1 for f in responded if f["verdict"] == "maybe"),
                "no_hire": sum(1 for f in responded if f["verdict"] == "no_hire"),
            },
            "feedback": feedback,
        }

    @mcp.tool()
    async def generate_shortlist(job_id: str = "job-001", top_n: int = 3) -> dict:
        """Compile the final shortlist from fit scores, rankings, and feedback."""
        shortlist = [
            {
                "rank": 1, "candidate_id": "c-001", "name": "Alice Hartman",
                "fit_score": 0.94, "verdict": "strong_hire",
                "rationale": "Highest composite score; exceptional technical depth; all 5 required skills confirmed.",
            },
            {
                "rank": 2, "candidate_id": "c-002", "name": "Raj Patel",
                "fit_score": 0.91, "verdict": "hire",
                "rationale": "Strong communicator; solid problem-solving; all required skills present.",
            },
            {
                "rank": 3, "candidate_id": "c-003", "name": "Sofia Mendes",
                "fit_score": 0.89, "verdict": "hire",
                "rationale": "Deep FastAPI/PostgreSQL experience; excellent culture fit; recommended as backup.",
            },
        ][:top_n]
        return {
            "observation": (
                f"Final shortlist for job '{job_id}': {len(shortlist)} candidates — "
                + "; ".join(
                    f"#{c['rank']} {c['name']} (score {c['fit_score']}, {c['verdict']})"
                    for c in shortlist
                )
                + ". Decision rationale logged per candidate."
            ),
            "job_id": job_id,
            "shortlisted": len(shortlist),
            "candidates": shortlist,
        }

    return mcp


def main() -> None:
    server = build_server()
    server.run()  # stdio transport


if __name__ == "__main__":
    main()
