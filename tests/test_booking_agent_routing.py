"""Guard: every surface that answers a visitor routes booking assistants to the
booking agent.

The reported symptom was an assistant with appointments enabled cheerfully
saying "you're booked for 3pm" while the Appointments page stayed empty.

The cause was a missing branch, not a broken tool. `POST /sessions/{id}/messages`
routed to `AskFrontOffice` and WhatsApp did too, but `POST /sessions/{id}/stream`
and the public widget ran plain retrieval — with no scheduling tools at all. A
model with no tools cannot check availability or write a booking, was never told
so, and answered as if it had. The builder's Test panel, the share page and the
embed all use the streaming path, which is why the same assistant appeared to
work over WhatsApp and nowhere else.

The check is deliberately at source level. What went wrong was one entry point
being written without the branch its siblings had, and the only property that
catches that is "all of them mention it" — an end-to-end test per surface would
have passed on the three that were already right and never been written for the
one that was not.
"""

from __future__ import annotations

import pathlib

import pytest

from src.interfaces.api.routers.chat import _as_chunks

ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "src" / "interfaces" / "api" / "routers"

# Every module that turns a visitor's message into an answer. Adding another
# one means adding it here — which is the point.
ANSWERING_ROUTERS = ["chat.py", "public.py", "whatsapp_web.py", "whatsapp_cloud.py"]


@pytest.mark.parametrize("module", ANSWERING_ROUTERS)
def test_an_answering_surface_checks_whether_the_assistant_books(module: str) -> None:
    source = (ROUTERS / module).read_text(encoding="utf-8")
    assert "appointments_enabled" in source, (
        f"{module} answers visitors but never asks whether the assistant books "
        "appointments — it will reply without tools and invent the booking"
    )


@pytest.mark.parametrize("module", ANSWERING_ROUTERS)
def test_an_answering_surface_can_reach_the_booking_agent(module: str) -> None:
    source = (ROUTERS / module).read_text(encoding="utf-8")
    assert "AskFrontOffice" in source, f"{module} has no path to the booking agent"


def test_the_streaming_endpoint_branches_before_it_retrieves() -> None:
    # Specifically the endpoint that was wrong. The branch has to come before
    # the retrieval graph is built, or a booking assistant pays for an
    # embedding and a vector search whose results it then ignores.
    source = (ROUTERS / "chat.py").read_text(encoding="utf-8")
    stream = source[source.index("async def ask_stream(") :]
    branch = stream.index("appointments_enabled")
    retrieval = stream.index("RagGraph(")
    assert branch < retrieval, "ask_stream retrieves before deciding who answers"


# --- the streaming contract the agent has to fit into ------------------------
#
# The agent is a tool loop: it has an answer or it does not, so there is nothing
# to stream while it runs. Chunking afterwards is what lets it reuse the same
# citations/token/done sequence the retrieval path emits, so no client needs a
# branch of its own.


def test_chunking_never_changes_the_answer() -> None:
    answer = "You're booked for Thursday at 6:15 pm with John. Reference AP-1042."
    assert "".join(_as_chunks(answer)) == answer


def test_chunking_preserves_newlines_and_runs_of_space() -> None:
    # A reply that formats a time or a reference across lines must arrive
    # looking the way the agent wrote it.
    answer = "Booked.\n\nThursday  6:15 pm\nRef: AP-1042"
    assert "".join(_as_chunks(answer)) == answer


def test_a_long_answer_arrives_in_several_pieces() -> None:
    # If it came as one chunk the reply would appear all at once, which reads
    # as a different, broken feature next to every other reply in the app.
    answer = " ".join(f"word{i}" for i in range(40))
    assert len(_as_chunks(answer)) > 1


def test_a_short_answer_is_a_single_chunk() -> None:
    assert _as_chunks("Booked.") == ["Booked."]


def test_an_empty_answer_yields_nothing_to_send() -> None:
    # Not [""] — an empty token event would render as a blank bubble.
    assert _as_chunks("") == []
