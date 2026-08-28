// Manual booking (spec section 8).
//
// The rule this component exists to honour: the browser never decides that a
// time is free. It asks the server for slots and lets the user pick one of
// them — there is no free-text time field, and no client-side "is this
// available?" arithmetic. That is the same guarantee the AI booking path gets,
// for the same reason.
import { FormEvent, useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2 } from "lucide-react";
import { ApiError } from "../api/client";
import {
  Appointment,
  Location,
  Service,
  Slot,
  appointmentsApi,
  availabilityApi,
  formatTimeInZone,
  locationsApi,
  servicesApi,
} from "../api/appointments";

/** A local Date as the "YYYY-MM-DD" an <input type=date> wants. */
function toDateInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export default function BookAppointmentModal({
  initialDate,
  onBooked,
  onClose,
}: {
  initialDate?: Date;
  onBooked: (appointment: Appointment) => void;
  onClose: () => void;
}) {
  const [locations, setLocations] = useState<Location[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [locationId, setLocationId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [date, setDate] = useState(toDateInput(initialDate ?? new Date()));

  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [zone, setZone] = useState("UTC");
  const [chosen, setChosen] = useState<Slot | null>(null);

  const [customer, setCustomer] = useState({ name: "", phone: "", email: "", notes: "" });

  const [loadingSetup, setLoadingSetup] = useState(true);
  const [loadingSlots, setLoadingSlots] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A key generated once per open, so a double-submit or a retry after a
  // timeout returns the booking already made rather than creating a second.
  const [idempotencyKey] = useState(
    () => `ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  );

  useEffect(() => {
    (async () => {
      try {
        const [locs, svcs] = await Promise.all([
          locationsApi.list(true),
          servicesApi.list(true),
        ]);
        setLocations(locs);
        setServices(svcs);
        if (locs.length > 0) setLocationId(locs[0].id);
        if (svcs.length > 0) setServiceId(svcs[0].id);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load the form.");
      } finally {
        setLoadingSetup(false);
      }
    })();
  }, []);

  // Re-ask the server whenever the question changes. Slots are never cached
  // across a change of service, branch or day: a stale list is a slot the
  // customer is told they can have and then cannot.
  useEffect(() => {
    if (!locationId || !serviceId || !date) return;
    let cancelled = false;
    (async () => {
      setLoadingSlots(true);
      setError(null);
      setChosen(null);
      try {
        const dayStart = new Date(`${date}T00:00:00`);
        const dayEnd = new Date(dayStart.getTime() + 24 * 60 * 60 * 1000);
        const result = await availabilityApi.find({
          location_id: locationId,
          service_id: serviceId,
          range_start: dayStart.toISOString(),
          range_end: dayEnd.toISOString(),
        });
        if (cancelled) return;
        setSlots(result.slots);
        setZone(result.timezone);
      } catch (err) {
        if (cancelled) return;
        setSlots([]);
        setError(
          err instanceof ApiError ? err.message : "Could not load available times.",
        );
      } finally {
        if (!cancelled) setLoadingSlots(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [locationId, serviceId, date]);

  async function handleBook(e: FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    setSaving(true);
    setError(null);
    try {
      const appointment = await appointmentsApi.create({
        location_id: locationId,
        service_id: serviceId,
        // The exact instant the server offered — never a time this form built.
        starts_at: chosen.starts_at,
        customer_name: customer.name,
        customer_phone: customer.phone,
        customer_email: customer.email,
        customer_notes: customer.notes,
        source: "staff",
        status: "confirmed",
        idempotency_key: idempotencyKey,
      });
      onBooked(appointment);
      onClose();
    } catch (err) {
      // A 409 is the expected outcome of a race, not a bug. Say what happened
      // and refresh the list rather than leaving a dead form.
      if (err instanceof ApiError && err.status === 409) {
        setError(`${err.message} The times below have been refreshed.`);
        setChosen(null);
        setDate((d) => d); // no-op; the effect below re-runs on the retry click
        try {
          const dayStart = new Date(`${date}T00:00:00`);
          const dayEnd = new Date(dayStart.getTime() + 24 * 60 * 60 * 1000);
          const result = await availabilityApi.find({
            location_id: locationId,
            service_id: serviceId,
            range_start: dayStart.toISOString(),
            range_end: dayEnd.toISOString(),
          });
          setSlots(result.slots);
        } catch {
          // The error above is already shown; a failed refresh adds nothing.
        }
      } else {
        setError(
          err instanceof ApiError ? err.message : "Could not book this appointment.",
        );
      }
    } finally {
      setSaving(false);
    }
  }

  const canBook = !!chosen && customer.name.trim() && (customer.phone || customer.email);
  const notConfigured =
    !loadingSetup && (locations.length === 0 || services.length === 0);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="New appointment"
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        onSubmit={handleBook}
        className="card shadow-modal w-full max-w-2xl max-h-[90vh] overflow-y-auto animate-scale-in"
      >
        <div className="px-6 py-4 border-b chrome-rule">
          <h2 className="text-sm font-semibold text-gray-900">New appointment</h2>
        </div>

        {loadingSetup ? (
          <div className="px-6 py-8 space-y-3" aria-busy="true">
            <div className="skeleton h-10 w-full" />
            <div className="skeleton h-10 w-full" />
            <div className="skeleton h-24 w-full" />
          </div>
        ) : notConfigured ? (
          <div className="px-6 py-8">
            <div className="empty-state">
              <AlertTriangle className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
              <p className="empty-state-title">Not set up for booking yet</p>
              <p className="empty-state-desc">
                You need at least one active location and one active service before
                an appointment can be made.
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="px-6 py-5 space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="label" htmlFor="book-location">
                    Location
                  </label>
                  <select
                    id="book-location"
                    className="input"
                    value={locationId}
                    onChange={(e) => setLocationId(e.target.value)}
                  >
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="book-service">
                    Service
                  </label>
                  <select
                    id="book-service"
                    className="input"
                    value={serviceId}
                    onChange={(e) => setServiceId(e.target.value)}
                  >
                    {services.map((service) => (
                      <option key={service.id} value={service.id}>
                        {service.name} ({service.duration_minutes}m)
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="book-date">
                    Date
                  </label>
                  <input
                    id="book-date"
                    type="date"
                    className="input"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </div>
              </div>

              {/* --- Times, straight from the availability engine --- */}
              <fieldset>
                <legend className="label">
                  Available times{" "}
                  <span className="font-normal text-gray-400">({zone})</span>
                </legend>

                {loadingSlots ? (
                  <div
                    className="flex items-center gap-2 text-sm text-gray-500 py-4"
                    aria-busy="true"
                  >
                    <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                    Checking availability…
                  </div>
                ) : slots && slots.length > 0 ? (
                  <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
                    {slots.map((slot) => {
                      const selected = chosen?.starts_at === slot.starts_at;
                      return (
                        <button
                          key={slot.starts_at}
                          type="button"
                          aria-pressed={selected}
                          onClick={() => setChosen(slot)}
                          className={`rounded-full border px-3.5 py-1.5 text-[13px] font-semibold
                                      tabular-nums transition-colors ${
                                        selected
                                          ? "border-brand-400 bg-brand-500 text-white"
                                          : "chrome-rule text-gray-600 hover:text-gray-900"
                                      }`}
                        >
                          {formatTimeInZone(slot.starts_at, zone)}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 py-4">
                    Nothing available that day. Try another date, or check the
                    service has eligible staff and the branch has opening hours.
                  </p>
                )}
              </fieldset>

              {/* --- Customer --- */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label" htmlFor="book-name">
                    Customer name *
                  </label>
                  <input
                    id="book-name"
                    required
                    className="input"
                    value={customer.name}
                    onChange={(e) => setCustomer({ ...customer, name: e.target.value })}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="book-phone">
                    Phone
                  </label>
                  <input
                    id="book-phone"
                    className="input"
                    value={customer.phone}
                    onChange={(e) => setCustomer({ ...customer, phone: e.target.value })}
                    placeholder="+971 50 123 4567"
                  />
                </div>
              </div>

              <div>
                <label className="label" htmlFor="book-email">
                  Email
                </label>
                <input
                  id="book-email"
                  type="email"
                  className="input"
                  value={customer.email}
                  onChange={(e) => setCustomer({ ...customer, email: e.target.value })}
                />
                <p className="text-xs text-gray-400 mt-1">
                  A phone number or an email is required — without one there is no
                  way to send a confirmation or a reminder.
                </p>
              </div>

              <div>
                <label className="label" htmlFor="book-notes">
                  Notes
                </label>
                <textarea
                  id="book-notes"
                  rows={2}
                  className="input"
                  value={customer.notes}
                  onChange={(e) => setCustomer({ ...customer, notes: e.target.value })}
                />
              </div>

              {error && (
                <div
                  role="alert"
                  className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
                >
                  {error}
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t chrome-rule">
              <button type="button" onClick={onClose} className="btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={saving || !canBook} className="btn-primary">
                {saving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" strokeWidth={2} />
                    Booking…
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4" strokeWidth={2} />
                    Book appointment
                  </>
                )}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
