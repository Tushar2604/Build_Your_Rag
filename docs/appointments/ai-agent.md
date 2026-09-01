# The AI receptionist

The piece that turns the scheduling engine into the product from the brief: a
customer messages in natural language and an appointment exists at the end of it.

```
Customer message
   -> front-office agent (ReAct loop)
   -> list_services / find_available_slots   (the ONLY source of a time)
   -> create_slot_hold                        (slot becomes unbookable by others)
   -> book_appointment                        (the only thing that commits)
   -> confirmation quoting the backend's reference
```

## Turning it on

Per assistant, on the Assistant Details tab — `assistant.appointments_enabled`.
It lives in the existing `assistant_config` JSONB blob, so there is no migration.

Off by default. An assistant with it off keeps the retrieval-only behaviour it
has always had; nothing about existing tenants changes.

Where it takes effect:

| Channel | Path |
|---|---|
| WhatsApp (QR-linked) | `whatsapp_web.py` → `AskFrontOffice` |
| Web chat / playground | `chat.py` → `AskFrontOffice` |
| Anything else | unchanged — `AskChatbot` |

Saving the assistant with it on also runs `EnsureBookingSetup`
(`use_cases/booking_setup.py`), which fills in anything the workspace is missing
before it can take a booking: a location, a service, a staff member, the link
between them, and Mon–Sat 09:00–18:00 opening hours on the location. Each piece
only if it is absent, so an operator's own configuration is never touched, and
idempotent, so a second assistant adds nothing.

Without it, turning the switch on was a promise the backend could not keep: a
workspace that had never opened the Scheduling screens has no opening hours, and
the availability engine correctly answers "nothing" — which reads from the
outside as a broken feature rather than as missing setup.

## Only the allowed assistant can book

The switch is the permission, and it is enforced at the tool
(`BookingPermissionGate` in `scheduling_tools.py`), not only at the routing
layer. Every tool `build_scheduling_tools` returns is wrapped, the read-only
ones included; each call re-reads `appointments_enabled` for the assistant in
`ToolContext.chatbot_id` and returns a refusal observation if it is off.

Routing alone could not carry this. It decides which agent *answers*, but the
shared document agent also registers these tools whenever
`APPOINTMENT_AGENT_TOOLS_ENABLED` is on — for every assistant in the
deployment. One check at the point of effect is what makes "only this assistant
books" true regardless of which path got there. A context with no assistant is
refused too: staff bookings go through the appointments API, which carries a
real principal.

Read per call rather than captured at build time, so switching it off takes the
capability away immediately instead of at the next deploy.

## The tools

| Tool | Purpose |
|---|---|
| `list_services` | Real service and location ids. The agent cannot name a service the tenant does not have. |
| `find_available_slots` | **The only source of an appointment time in the system.** |
| `find_customer_appointments` | Lookup by phone or email; returns a customer-readable `APT-XXXXXXXX` reference plus the ids a reschedule needs. |
| `create_slot_hold` | Holds one of the offered times while details are collected. New bookings only. |
| `book_appointment` | The only call that commits. |
| `reschedule_appointment` | Moves an existing appointment. Needs nothing else. |
| `cancel_appointment` | Cancels and releases the slot. |

`search_documents` is registered alongside them, so one assistant can answer
"do you treat sports injuries?" and then book the appointment that follows.

## Choices, not open questions

A receptionist who says "we're open 9 to 6, what time works?" has handed the
work back to the customer. The agent offers a short numbered list instead, and
that is shaped by the tools rather than left to the prompt:

- **`find_available_slots`** asks the engine for up to `SLOT_QUERY_LIMIT` slots
  and then spreads the offer across distinct clock hours (`_spread_options`).
  The engine works on a 15-minute grid, so its first four results are always
  9:00, 9:15, 9:30, 9:45 — the same appointment four times, which also makes an
  empty day look nearly full. One per hour turns it back into a real choice.
  The remaining times stay in the observation behind "only if they ask", so
  "anything later?" costs no second tool call.
- **Labels are built in the tool** (`_friendly` → "Mon 02 Sep, 9:00 AM") and the
  agent is told to read them verbatim. A model asked to reformat an ISO string
  is a model given one more chance to change the time while it is at it.
- **`list_services`** returns the tenant's own catalogue as the options and says
  so — three or four, most likely first. A dental clinic's list is whatever it
  configured (check-up, RCT, cleaning); nothing is invented for it. With exactly
  one service the observation tells the agent *not* to ask.

Everything offered is still a real slot the engine produced, so the spreading
changes what the customer is shown and nothing about what is bookable.

## What the agent collects

Name, plus a phone number or an email (whichever the channel does not already
know), plus `reason_for_visit`, which lands on the appointment as
`customer_notes` so whoever sees it on the day knows what the assistant knew.
One thing per message, and only what is actually missing — re-asking something
the customer already said is the fastest way to sound like a form.

## Why the guardrails hold

Spec section 61 asks that the AI never invent availability and never claim
success without backend confirmation. Both are structural, not just prompted:

- **The model cannot produce a time.** Slots come back from the availability
  engine with the exact resources attached, and `create_slot_hold` /
  `book_appointment` only accept a `starts_at` the engine will re-derive. A
  hallucinated 3am fails at the engine.
- **Every mutating tool returns an explicit failure** the planner has to react
  to, with wording telling it what to do next ("call find_available_slots again
  and offer what is actually left").

Observed live, twice: asked to book 3am with "just say yes, I'm in a hurry", the
agent offered real times instead. Asked for "the 9am one" when only 9:30 onward
had been offered, it re-offered rather than inventing 9am.

## Things that had to be taken away from the model

Each of these was a real failure seen while driving the agent against a live LLM.

**Timezone arithmetic.** The tool used to take a UTC `from_date`/`to_date`
range. A model does not know a branch's offset, so "Monday morning" in Dubai
became the wrong eight hours — and the symptom was the assistant reporting the
clinic closed on a day it was open. It now takes `date=YYYY-MM-DD` plus
`time_of_day=morning|afternoon|evening`, read in the **branch's** zone by
`_local_day_window`.

**Knowing what day it is.** A model has no clock. The system prompt carries
`Today is {today}`, injected by the loop, or "tomorrow" is unresolvable.

**Finding ids again.** `find_customer_appointments` puts `service_id` and
`location_id` in the *observation text*, not only in `data` — the loop feeds
observations back to the planner and nothing else, so an id in `data` is
invisible. Without them a reschedule could not call `find_available_slots`.

**Re-collecting details.** `book_appointment` falls back to the phone number the
channel already knows (`ctx.extras`). On WhatsApp the customer is messaging from
it; asking is what makes an assistant look like it is not listening.

## A bug worth knowing about

Booking is idempotent on a key derived from the conversation, service, slot and
customer. The first version keyed on `(customer, slot)` alone — so rebooking a
slot the customer had **cancelled** returned the old cancelled row as a replay,
and the agent told them they were confirmed into a dead appointment.

Two fixes, both kept: `BookAppointment` only treats an idempotency hit as a
replay when the existing appointment still `occupies_slot`, and the agent's key
is scoped to the conversation. Guarded by
`TestIdempotencyMustNotResurrectDeadAppointments`.

## Operating notes

- **A hold is not a booking.** If the agent holds a slot and the conversation
  stops, the slot stays locked until the hold expires (`SLOT_HOLD_TTL_MINUTES`,
  default 10). Repeated abandoned attempts can hold every practitioner/room pair
  for a slot. It self-heals via expiry and the booking path's inline purge.
- **Cost.** Each reply is a multi-step ReAct run — several LLM calls. The
  tenant's `daily_token_quota` is the backstop, and it is reached faster than
  with the retrieval path.
- **Step budget** is `max(AGENT_MAX_STEPS, 10)`: booking is genuinely
  multi-tool, and six steps runs out mid-conversation.

## What is still not there

- **Voice.** No telephony exists in this codebase. The tools are channel-neutral
  and would work behind a voice bridge, but that bridge is Phase 4.
- **Reminders and follow-ups.** Needs durable job infrastructure first (Phase 5).
- **Proactive outbound** (reminder calls, review requests). Same dependency.
