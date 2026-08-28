# Appointment schema

Migration `0025_scheduling_foundation`. Additive only — nothing existing is
altered, and `interviews` / `interview_batches` are untouched.

Every table carries `tenant_id`, is indexed on it, and has
`ENABLE ROW LEVEL SECURITY` plus a `tenant_isolation` policy keyed on
`current_setting('app.tenant_id')`, matching the rest of the schema.

## Tables

### `locations`
A branch. `timezone` is an IANA name and is the most consequential column in the
module: every weekly availability rule underneath it is resolved against it.
`slug` is unique **per tenant**, not globally — two businesses may both have a
"downtown".

### `services`
What a customer books. Duration, buffers, price (minor units — never a float),
deposit, minimum notice, booking horizon, cancellation window.

Buffers live here rather than on the appointment: the ten minutes after a
consultation are needed whoever books it, and putting them on the appointment
lets a booking path forget them.

### `resources`
Staff, rooms, equipment, vehicles — one table, discriminated by `kind`. The
availability engine ignores `kind` entirely; it exists for the UI and for
eligibility roles. Modelling staff separately is what makes a scheduler unable to
book a meeting room later.

`location_id` and `user_id` are both `ON DELETE SET NULL`: closing a branch must
not delete the doctors who worked there, and removing a login must not delete the
resource that existing appointments point at.

### `service_resources`
Which resources may serve which service, **and in what role**. The role is what
makes multi-resource booking expressible: a consultation requiring one
`practitioner` and one `room` is two rows with different roles, and the engine
fills every distinct required role before offering a slot.

Unique on `(service_id, resource_id, role)`.

### `availability_rules`
A recurring weekly window. `start_time` / `end_time` are `TIME` **without** a
zone, deliberately — see
[availability-engine.md](availability-engine.md#daylight-saving).

`owner_kind` + `owner_id` is polymorphic rather than two nullable foreign keys,
so the engine can load every rule for a query in one indexed statement. The
trade-off is that nothing in the schema stops a rule pointing at another tenant's
branch, so the router checks ownership explicitly.

### `blocked_periods`
Leave, holidays, maintenance. Absolute UTC intervals, not recurrences — these
genuinely are one-off ("that Tuesday off").

Creating a block stops **new** bookings; it never cancels appointments that
already exist. Silently cancelling someone's confirmed appointment because a
manager marked a day off would be worse than surfacing the clash for a human.

### `appointments`
The canonical booking. Every channel writes one of these and nothing else.

- `location_id` / `service_id` are `ON DELETE RESTRICT`: deleting a branch or a
  service must not silently erase the appointments booked against it. The UI
  deactivates instead.
- Customer identity is columns, not a foreign key — there is no CRM entity yet.
  The names match the entity that will replace them.
- `timezone` is copied from the branch at booking time, so correcting a branch's
  zone later cannot move appointments that already happened.
- `resource_ids` is a denormalized JSONB copy so a calendar render needs no join
  per appointment. `resource_reservations` remains the authority on what is
  actually booked.
- `idempotency_key` has a **partial** unique index
  (`WHERE idempotency_key <> ''`), so a retried POST cannot create a second
  booking while the many appointments booked without a key never collide on an
  empty string.

### `appointment_status_history`
Append-only. Never updated, never deleted while the appointment lives. Records
`from_status`, `to_status`, actor kind and id, channel, reason, timestamp — the
answer to "who cancelled this, and when".

`actor_kind` is deliberately distinct from the appointment's `source`: an AI can
create what a receptionist later cancels.

### `resource_reservations`
Claimed time — and the double-booking guard itself.

```sql
ALTER TABLE resource_reservations
ADD CONSTRAINT no_overlapping_reservations
EXCLUDE USING gist (
    resource_id WITH =,
    (tstzrange(starts_at, ends_at, '[)')) WITH &&
) WHERE (released_at IS NULL);
```

Holds and bookings are rows in the same table so they compete for the same time
on the same constraint. `starts_at`/`ends_at` include the service's buffers —
this is the calendar actually consumed, which is wider than the appointment the
customer sees.

The range is an **expression** over two ordinary timestamp columns rather than a
stored `tstzrange`, so the ORM writes plain datetimes and no driver-specific
range type is involved.

`released_at` rather than `DELETE`: a cancelled booking keeps its record of what
was held while dropping out of the constraint's scope, which is what lets a
cancelled slot be rebooked without losing the history that it once was not.

Requires `btree_gist`, created by the migration.

## Indexes worth knowing

| Index | Query it serves |
|---|---|
| `ix_resource_reservations_lookup` (partial, live rows) | The engine's busy-time lookup |
| `ix_resource_reservations_expiring` (partial, unreleased holds) | The expiry sweep — otherwise every tick scans every reservation ever made |
| `ix_availability_rules_owner` | Every rule for a set of owners, per weekday |
| `ix_appointments_tenant_window` | The calendar's day query |
| `ix_appointments_tenant_status_window` | The list view's status filter |
| `uq_appointments_idempotency_key` (partial) | Retry safety |

## Rollback

`alembic downgrade -1` drops all nine tables in dependency order (reservations →
appointments → locations). `btree_gist` is deliberately left installed: it is
shared infrastructure another feature may rely on.

Verified against a real Postgres 16: upgrade → downgrade → upgrade is clean.
`tests/test_scheduling_schema_parity.py` pins the constraint, the RLS policies,
the indexes, and the drop order without needing a database.
