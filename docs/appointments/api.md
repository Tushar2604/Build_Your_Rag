# Appointment API

All routes are under `/api/v1`, gated by `APPOINTMENTS_ENABLED`. Authentication
is the platform's existing Bearer JWT or `X-API-Key`; the tenant comes from the
principal and is never read from a request body.

**Configuration routes require Owner/Admin.** Availability search, booking, and
the lifecycle actions are open to any authenticated user, because receptionists
need them.

## Status codes that carry meaning

| Code | Meaning |
|---|---|
| `409` | **The slot has gone.** The expected outcome of a race, not an error. Re-query availability and offer what is actually left. |
| `422` | An illegal state transition, or invalid input. The message is written for a human ("An appointment that is cancelled cannot become completed"). |
| `404` | Not found **in your tenant**. Another tenant's id reads as absent, never as forbidden. |
| `200` on create | An idempotent replay — you already made this booking. |

## Configuration

```
GET    /locations?active_only=
POST   /locations
GET    /locations/{id}
PUT    /locations/{id}
DELETE /locations/{id}          deactivates; never deletes

GET    /services?active_only=
POST   /services
GET    /services/{id}
PUT    /services/{id}
PUT    /services/{id}/resources   replaces the whole eligibility set
DELETE /services/{id}             deactivates

GET    /resources?location_id=&kind=&active_only=
POST   /resources
GET    /resources/{id}
PUT    /resources/{id}
DELETE /resources/{id}            deactivates
```

Deletion is always deactivation: appointments reference locations and services
with `ON DELETE RESTRICT`, and a branch that closes still has history worth
keeping.

### Eligibility roles

`PUT /services/{id}/resources` takes the complete intended set:

```json
{
  "resources": [
    {"resource_id": "…", "role": "practitioner", "required": true},
    {"resource_id": "…", "role": "room",         "required": true}
  ]
}
```

Resources **sharing** a role are alternatives — any one free is enough.
Resources in **different** roles are all required simultaneously. A service whose
roles cannot all be filled produces no slots, and the Services page marks it
"Not bookable" rather than leaving an operator to conclude the calendar is
broken.

## Availability

```
GET /availability
    ?location_id=&service_id=&range_start=&range_end=
    [&resource_id=][&granularity_minutes=15][&limit=200]
```

The authoritative answer. Range is capped at 62 days.

```json
{
  "location_id": "…",
  "service_id": "…",
  "timezone": "Asia/Dubai",
  "duration_minutes": 30,
  "slots": [
    {
      "starts_at": "2026-09-01T05:00:00+00:00",
      "ends_at":   "2026-09-01T05:30:00+00:00",
      "resource_ids": ["…practitioner…", "…room…"]
    }
  ]
}
```

`resource_ids` is part of the contract, not decoration: booking this slot
reserves exactly these. `timezone` travels with the answer so a client can render
local time without a second lookup.

Note the ISO offset contains `+`, which must be URL-encoded in a query string.

### Rules and closures

```
GET    /availability-rules?owner_id=
POST   /availability-rules      { owner_kind, owner_id, weekday, start_time, end_time }
DELETE /availability-rules/{id}

GET    /blocked-periods?owner_id=
POST   /blocked-periods         { owner_kind, owner_id, starts_at, ends_at, reason }
DELETE /blocked-periods/{id}
```

`weekday` is Monday = 0. `start_time` / `end_time` are **local wall-clock**
("09:00"). `starts_at` / `ends_at` on a block are UTC instants.

## Slot holds

```
POST   /slot-holds     { location_id, service_id, starts_at, resource_id? }
DELETE /slot-holds/{token}
```

Claims a slot briefly (default 10 minutes) while a conversation finishes. `409`
if it has gone. Releasing an unknown or expired token succeeds — the caller
wanted the hold gone, and it is.

```json
{
  "token": "…",
  "starts_at": "…", "ends_at": "…", "expires_at": "…",
  "resource_ids": ["…"]
}
```

## Appointments

```
GET   /appointments
      ?range_start=&range_end=&location_id=&service_id=&resource_id=
      &status=confirmed,pending&search=&page=1&page_size=50
GET   /appointments/summary?range_start=&range_end=
POST  /appointments
GET   /appointments/{id}
PATCH /appointments/{id}                 details only
GET   /appointments/{id}/history
POST  /appointments/{id}/reschedule      { starts_at, resource_id?, reason? }
POST  /appointments/{id}/confirm
POST  /appointments/{id}/check-in
POST  /appointments/{id}/start
POST  /appointments/{id}/complete
POST  /appointments/{id}/cancel
POST  /appointments/{id}/no-show
```

### Creating

```json
{
  "location_id": "…",
  "service_id": "…",
  "starts_at": "2026-09-01T05:00:00+00:00",
  "customer_name": "Mohammed Ali",
  "customer_phone": "+971501234567",
  "hold_token": "",
  "source": "staff",
  "status": "pending",
  "idempotency_key": "…"
}
```

- `starts_at` must be a time `GET /availability` returned. Anything else is a
  `409` — the server resolves it through the engine rather than obeying it.
- A phone number **or** an email is required; without one there is no way to send
  a confirmation or a reminder.
- With a `hold_token`, the hold is converted in place by an `UPDATE`, so the slot
  is never free for an instant in between.
- `Idempotency-Key` may be sent as a header instead of a body field. A replay
  returns `200` with the original appointment.
- `source` is channel attribution and never changes after creation.

### Lifecycle

One endpoint per verb rather than a status `PATCH`, so the server can reject an
illegal move and record who made a legal one. `PATCH /appointments/{id}` edits
details only — moving an appointment in time goes through `/reschedule`, so a
general PATCH can never reach the reservation logic.

Legal transitions are in `src/domain/scheduling/entities.py::_TRANSITIONS`.

### History

```json
{
  "appointment_id": "…",
  "entries": [
    {"from_status": "", "to_status": "confirmed", "actor_kind": "staff",
     "actor_label": "", "channel": "dashboard", "reason": "",
     "occurred_at": "…"}
  ]
}
```

The first entry has an empty `from_status`: nothing preceded it, and inventing a
status would make the history claim a transition that never happened.

## AI agent tools

Registered in the shared agent loop when `APPOINTMENT_AGENT_TOOLS_ENABLED=true`
(off by default — turning it on changes the existing document-answering agent's
tool catalogue).

| Tool | Purpose |
|---|---|
| `list_services` | Real service and location ids. The agent cannot name a service the tenant does not have. |
| `find_available_slots` | The only source of an appointment time in the system. |
| `create_slot_hold` | Holds one of those exact times; `409` tells the agent to search again. |

The model has no way to produce a time, which is what makes "never invent a
slot" structural rather than a prompt instruction. `book_appointment` arrives
with the channel that needs it — booking on a customer's behalf requires identity
and consent context a channel supplies.

## Outbound webhooks

Not in this phase. The three domain events are already emitted and audited, so
the webhook dispatcher subscribes to them without touching the booking use case.
