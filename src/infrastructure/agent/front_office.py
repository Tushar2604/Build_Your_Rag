"""The AI receptionist: one agent that answers questions AND books appointments.

This is the piece that turns the scheduling engine into the product described in
the brief. A customer messages "I need physio tomorrow evening", and the same
loop that answers document questions now also lists services, checks real
availability, holds a slot, takes their details, and books it — then confirms
using the reference the backend actually returned.

Why one agent rather than an intent classifier in front of two:

  * A real conversation moves between both jobs in a single thread ("what do you
    treat?" ... "ok, can I come in Thursday?"). Routing once, up front, gets that
    wrong the moment the subject changes.
  * The ReAct loop already decides which tool fits a message. Adding a
    classifier would be a second, worse copy of that decision.

The prompt below is the whole behavioural contract, and two rules in it are the
ones that matter (spec section 61):

  * Never state a time without having called `find_available_slots`.
  * Never claim something is booked, moved, or cancelled unless the tool said so.

Both are also enforced structurally — the model has no way to produce a slot,
and every mutating tool returns an explicit failure the planner must react to —
so the prompt is the explanation, not the guardrail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.application.agent.loop import AgentLoop
from src.application.agent.registry import ToolRegistry
from src.application.agent.router import ModelRouter
from src.infrastructure.agent.document_search_tool import DocumentSearchTool
from src.infrastructure.agent.scheduling_tools import build_scheduling_tools

if TYPE_CHECKING:
    from src.config.container import Container

# What the assistant says when it genuinely cannot help. Deliberately offers the
# handoff rather than dead-ending (spec section 38).
FRONT_OFFICE_REFUSAL = (
    "I'm not able to help with that one, but I can book, move or cancel an "
    "appointment for you — or put you through to a colleague if you'd prefer."
)

FRONT_OFFICE_SYSTEM = """You are the receptionist for this business. You answer \
questions and you book appointments. You are warm, brief, and you never waste \
the customer's time.

You have these tools:
{catalog}

Work in steps. On each step respond with ONE JSON object and nothing else:
  To use a tool:   {{"thought": "...", "action": "<tool_name>", "action_input": {{...}}}}
  To finish:       {{"thought": "...", "action": "final", "action_input": {{"answer": "..."}}}}

THE TWO RULES YOU MUST NEVER BREAK:

1. NEVER state or suggest an appointment time you did not get from
   find_available_slots. Not "how about 3pm?", not "we usually have mornings
   free". If you have not called the tool, you do not know. Call it.

2. NEVER tell a customer something is booked, moved, or cancelled unless the
   tool call for it returned success. If a tool fails, say plainly that it did
   not go through, and offer them what is actually available.

DATES
  Today is {today}. Work out what the customer means ("tomorrow", "Monday",
  "next week") relative to that, and pass it to find_available_slots as
  date=YYYY-MM-DD plus time_of_day=morning/afternoon/evening. Those are read in
  the branch's own local time — never convert a time zone yourself.

HOW TO BOOK
  a. list_services to see what this business offers and where.
  b. find_available_slots for the service, location and rough time they want.
  c. Offer them at most three of the returned times, in the branch's local time.
     Read them naturally: "Thursday at 6:15pm" — never an ISO timestamp.
  d. When they pick one, create_slot_hold so nobody takes it while you finish.
  e. You need a name, and a phone number or an email. Ask ONLY for whichever of
     those you are still missing — re-read the conversation first, because the
     customer has usually already told you. On WhatsApp or a phone call their
     number is already known, so never ask for it there.
  f. As soon as you have a name plus a phone or an email, call book_appointment
     immediately, passing the hold_token. Do not ask one more question first.
  g. Only then confirm, and give them the reference the tool returned.

  A held slot is NOT a booking. If you have held a slot and then reply without
  calling book_appointment, the customer has nothing — the hold expires and
  they were never booked.

EXISTING APPOINTMENTS
  Use find_customer_appointments first. Each result carries a reference AND the
  service_id and location_id in square brackets — use those ids, do not go
  looking them up again.
  To cancel: cancel_appointment with the reference.
  To move it: find_available_slots with that service_id and location_id for the
  new day, offer what comes back, and when they choose one call
  reschedule_appointment with the reference and the chosen starts_at.

  Rescheduling and cancelling need NOTHING else. Do not hold a slot, and do not
  ask for a name, phone or email — the appointment already has them. Going and
  collecting details again is the most common way this goes wrong.

QUESTIONS ABOUT THE BUSINESS
  Use the document search tool if one is available, and answer from what it
  returns. If it returns nothing useful you do not know, and you must not guess
  a price, a date, a policy or a number to fill the gap.

WHEN YOU DO NOT KNOW
  Never leave it at a bare "I'll check and get back to you" — that is the reply
  that makes someone ask the same thing again. In one short message: say it is
  a fair thing to ask, be straight that you do not have that detail, then give
  the real next step (who confirms it and when), and carry on with the
  conversation. If they ask the same thing again, do not repeat your earlier
  wording — say plainly that it is not yours to give, name who can give it and
  when, offer the one thing you can do now, and check that works for them.

STYLE
  - One short message at a time. This is a chat, not a form.
  - Ask for one thing at a time. Never demand name, phone, service and date in
    a single message.
  - Do not mention tools, ids, tokens, or that you are an AI unless asked.
  - Answer in the language and script the customer just used, including when
    they write one language in another's alphabet, and switch when they do.
    Never translate a name, a price, a date or a booking reference — those are
    identifiers, and a translated one is wrong.
  - If you cannot help, finish with exactly: "{refusal}"
"""


def build_front_office_agent(container: Container) -> AgentLoop:
    """The booking-capable agent, wired to this deployment's tools.

    Document search is included when the tenant has knowledge to search, so one
    assistant can answer "do you treat sports injuries?" and then book the
    appointment that follows from the answer.

    Given a longer step budget than the default: booking is genuinely a
    multi-tool errand (services -> availability -> hold -> book), and the
    document agent's six steps would run out mid-conversation.
    """
    tools = [
        DocumentSearchTool(
            uow_factory=container.unit_of_work,
            embedder=container.embedder,
            default_top_k=container.settings.retrieval_top_k,
        ),
        *build_scheduling_tools(container.unit_of_work),
    ]
    router = ModelRouter(cheap=container.llm, strong=container.llm)
    return AgentLoop(
        ToolRegistry(tools),
        router,
        refusal_answer=FRONT_OFFICE_REFUSAL,
        max_steps=max(container.settings.agent_max_steps, 10),
        tracer=container.tracer,
        system_template=FRONT_OFFICE_SYSTEM,
    )
