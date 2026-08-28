# Appointments

The scheduling engine: locations, services, resources, availability, and
appointments — one engine that every channel books through.

Phase 1 (this document set) covers the scheduling core and the staff-facing UI.
WhatsApp booking, voice booking, reminders, waitlist, payments and public
booking pages are later phases; see [Roadmap](#roadmap).

## The two ideas that matter

**Availability is computed in one place, and only there.** The dashboard, the
API, and (later) the WhatsApp and voice agents all call the same
`GET /api/v1/availability`. Nothing else in the system is allowed to decide that
a time is free. That is what makes "the AI must never invent a slot" a
structural property rather than a prompt instruction — there is no other source
of an appointment time.

**Double-booking is prevented by Postgres, not by application code.** Holds and
bookings are rows in one table guarded by a GiST exclusion constraint. Two
customers who ask for 3:00 PM in the same instant cannot both win, regardless of
transaction interleaving or how many web workers are running. See
[availability-engine.md](availability-engine.md#concurrency).

## Quick start

1. **Locations** — add a branch. Its IANA timezone is the clock every opening
   hour underneath it is read against.
2. **Resources** — add the people, rooms, and equipment appointments consume.
3. **Services** — add what customers book, then assign eligible resources *and
   the role each fills*. A service requiring a `practitioner` and a `room` only
   produces a slot when one of each is free at the same time.
4. **Availability** — set weekly opening hours. A branch with no hours is
   treated as closed, not as always open.
5. **Calendar** — book, confirm, check in, complete.

## Documents

| File | What it covers |
|---|---|
| [architecture.md](architecture.md) | Layering, where each piece lives, what is deliberately deferred |
| [database.md](database.md) | The nine tables, their constraints, and why each one is shaped that way |
| [api.md](api.md) | Every endpoint, with the status codes that carry meaning |
| [availability-engine.md](availability-engine.md) | The slot calculation, timezones, and the concurrency guard |
| [testing.md](testing.md) | What is tested where, and the one test that needs a real database |

## Feature flags

| Setting | Default | Effect |
|---|---|---|
| `APPOINTMENTS_ENABLED` | `true` | Mounts the module's routes and the hold-expiry sweep |
| `APPOINTMENT_AGENT_TOOLS_ENABLED` | `false` | Gives the shared agent loop the booking tools. Off until a channel is wired to use them — turning it on changes the existing document-answering agent's tool catalogue |
| `SLOT_HOLD_TTL_MINUTES` | `10` | How long a held slot survives without being converted |

## Roadmap

| Phase | Content | Status |
|---|---|---|
| 1 | Scheduling core, availability, concurrency, calendar UI, manual booking | **Done** |
| 2 | Public booking page + widget, customer entity, intake forms | Not started |
| 3 | WhatsApp appointment agent | Not started |
| 4 | Twilio Voice telephony + voice booking | Not started |
| 5 | Durable job infrastructure, then reminder rules | Not started |
| 6 | Waitlist, payments, recurrence, QR check-in, two-way calendar sync | Not started |
| 7 | Appointment analytics and channel attribution | Not started |
| 8 | Granular RBAC, performance, accessibility, webhook retry/replay | Not started |

Phase 5 lists job infrastructure before reminders deliberately: this deployment
has one `asyncio` sweep loop and no queue, and reminders are not buildable on
that.
