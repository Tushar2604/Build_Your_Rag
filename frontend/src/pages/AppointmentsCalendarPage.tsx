// The operational calendar: a day at a glance, one column per resource.
//
// Built rather than imported. This project has no calendar dependency and a
// bespoke design system, so a third-party grid would arrive with its own
// styling to fight and its own timezone opinions to correct — and the timezone
// handling is the part that has to be right. Every position on this grid is
// derived from `minutesFromMidnight` in the BRANCH's zone, never the browser's.
import { useEffect, useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { ApiError } from "../api/client";
import AppointmentDrawer from "../components/AppointmentDrawer";
import BookAppointmentModal from "../components/BookAppointmentModal";
import {
  Appointment,
  Location,
  Resource,
  appointmentsApi,
  formatTimeInZone,
  locationsApi,
  minutesFromMidnight,
  resourcesApi,
  statusBadgeClass,
  statusLabel,
} from "../api/appointments";

// The visible day. Wide enough for most businesses; appointments outside it are
// still listed below the grid rather than hidden.
const DAY_START_HOUR = 7;
const DAY_END_HOUR = 21;
const PIXELS_PER_MINUTE = 1;
const GRID_HEIGHT = (DAY_END_HOUR - DAY_START_HOUR) * 60 * PIXELS_PER_MINUTE;

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function dayBounds(date: Date): { start: Date; end: Date } {
  const start = new Date(date);
  start.setHours(0, 0, 0, 0);
  return { start, end: addDays(start, 1) };
}

/** Statuses that no longer occupy the calendar — shown faded, not hidden, so a
 *  receptionist can see that a slot opened up rather than wondering. */
const RELEASED = new Set(["cancelled", "no_show", "rescheduled"]);

export default function AppointmentsCalendarPage() {
  const [date, setDate] = useState(() => new Date());
  const [locations, setLocations] = useState<Location[]>([]);
  const [locationId, setLocationId] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const locs = await locationsApi.list(true);
        setLocations(locs);
        if (locs.length > 0) setLocationId(locs[0].id);
        else setAppointments([]);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load locations.");
      }
    })();
  }, []);

  async function load() {
    if (!locationId) return;
    setError(null);
    setAppointments(null);
    try {
      const { start, end } = dayBounds(date);
      const [page, res] = await Promise.all([
        appointmentsApi.list({
          range_start: start.toISOString(),
          range_end: end.toISOString(),
          location_id: locationId,
          page_size: 200,
        }),
        resourcesApi.list({ locationId, activeOnly: true }),
      ]);
      setAppointments(page.appointments);
      setResources(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the calendar.");
      setAppointments([]);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locationId, date]);

  const zone =
    locations.find((l) => l.id === locationId)?.timezone ||
    Intl.DateTimeFormat().resolvedOptions().timeZone;

  // Columns: only resources that can actually hold an appointment, plus a
  // catch-all for anything whose resource is not in this branch's list.
  const columns = useMemo(() => {
    const withAppointments = new Set(
      (appointments ?? []).flatMap((a) => a.resource_ids),
    );
    const shown = resources.filter(
      (r) => r.kind !== "equipment" || withAppointments.has(r.id),
    );
    return shown.length > 0 ? shown : resources;
  }, [resources, appointments]);

  const unplaced = (appointments ?? []).filter(
    (a) => !a.resource_ids.some((id) => columns.some((c) => c.id === id)),
  );

  function positionOf(appointment: Appointment) {
    const startMinutes = minutesFromMidnight(appointment.starts_at, zone);
    const endMinutes = minutesFromMidnight(appointment.ends_at, zone);
    const top = (startMinutes - DAY_START_HOUR * 60) * PIXELS_PER_MINUTE;
    // An appointment ending at or past midnight reads as 0; clamp so it draws
    // to the bottom of the grid rather than collapsing to nothing.
    const rawHeight = (endMinutes > startMinutes ? endMinutes - startMinutes : 30) *
      PIXELS_PER_MINUTE;
    return { top, height: Math.max(rawHeight, 22) };
  }

  const hours = Array.from(
    { length: DAY_END_HOUR - DAY_START_HOUR },
    (_, i) => DAY_START_HOUR + i,
  );

  const isToday = new Date().toDateString() === date.toDateString();

  function replace(updated: Appointment) {
    setAppointments((current) =>
      (current ?? []).map((a) => (a.id === updated.id ? updated : a)),
    );
    setSelected(updated);
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Calendar</h1>
          <p className="page-subtitle">
            {date.toLocaleDateString(undefined, {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
            {zone && <span className="text-gray-400"> · {zone}</span>}
          </p>
        </div>
        <div className="page-header-actions">
          {locations.length > 1 && (
            <select
              aria-label="Location"
              className="input py-1.5 w-auto"
              value={locationId}
              onChange={(e) => setLocationId(e.target.value)}
            >
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </select>
          )}
          <div className="segmented">
            <button
              className="segmented-item"
              onClick={() => setDate((d) => addDays(d, -1))}
              aria-label="Previous day"
            >
              <ChevronLeft className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              className={isToday ? "segmented-item-active" : "segmented-item"}
              onClick={() => setDate(new Date())}
            >
              Today
            </button>
            <button
              className="segmented-item"
              onClick={() => setDate((d) => addDays(d, 1))}
              aria-label="Next day"
            >
              <ChevronRight className="w-4 h-4" strokeWidth={2} />
            </button>
          </div>
          <button className="btn-primary" onClick={() => setBooking(true)}>
            <Plus className="w-4 h-4" strokeWidth={2} />
            New appointment
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
        >
          {error}{" "}
          <button onClick={load} className="underline font-medium">
            Retry
          </button>
        </div>
      )}

      {locations.length === 0 && appointments !== null && (
        <div className="empty-state">
          <CalendarDays className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">Nothing to show yet</p>
          <p className="empty-state-desc">
            Add a location, a service, and someone to deliver it — then the
            calendar has something to draw.
          </p>
        </div>
      )}

      {appointments === null && locationId && (
        <div className="skeleton w-full" style={{ height: GRID_HEIGHT / 2 }} aria-busy="true" />
      )}

      {appointments !== null && locationId && columns.length === 0 && (
        <div className="empty-state">
          <CalendarDays className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">No bookable resources here</p>
          <p className="empty-state-desc">
            This branch has no active staff or rooms, so there are no columns to
            draw. Add a resource to get started.
          </p>
        </div>
      )}

      {appointments !== null && columns.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <div className="min-w-[640px]">
              {/* Column headers */}
              <div
                className="grid border-b chrome-rule"
                style={{
                  gridTemplateColumns: `64px repeat(${columns.length}, minmax(140px, 1fr))`,
                }}
              >
                <div />
                {columns.map((resource) => (
                  <div
                    key={resource.id}
                    className="px-3 py-2.5 text-[13px] font-semibold text-gray-700 truncate"
                  >
                    {resource.name}
                  </div>
                ))}
              </div>

              {/* Grid */}
              <div
                className="relative grid"
                style={{
                  gridTemplateColumns: `64px repeat(${columns.length}, minmax(140px, 1fr))`,
                  height: GRID_HEIGHT,
                }}
              >
                {/* Hour gutter */}
                <div className="relative border-r chrome-rule">
                  {hours.map((hour, index) => (
                    <div
                      key={hour}
                      className="absolute right-2 text-[11px] tabular-nums text-gray-400"
                      style={{ top: index * 60 * PIXELS_PER_MINUTE - 6 }}
                    >
                      {String(hour).padStart(2, "0")}:00
                    </div>
                  ))}
                </div>

                {columns.map((resource) => {
                  const forResource = (appointments ?? []).filter((a) =>
                    a.resource_ids.includes(resource.id),
                  );
                  return (
                    <div key={resource.id} className="relative border-r chrome-rule">
                      {/* Hour lines */}
                      {hours.map((hour, index) => (
                        <div
                          key={hour}
                          className="absolute inset-x-0 border-t chrome-rule"
                          style={{ top: index * 60 * PIXELS_PER_MINUTE }}
                        />
                      ))}

                      {forResource.map((appointment) => {
                        const { top, height } = positionOf(appointment);
                        const released = RELEASED.has(appointment.status);
                        return (
                          <button
                            key={appointment.id}
                            onClick={() => setSelected(appointment)}
                            style={{ top, height }}
                            className={`absolute inset-x-1 overflow-hidden rounded-lg border px-2 py-1
                                        text-left text-[11px] leading-tight transition-shadow
                                        hover:shadow-md ${
                                          released
                                            ? "border-gray-200 bg-gray-100/70 text-gray-400 line-through"
                                            : "border-brand-400/40 bg-brand-500/15 text-gray-800"
                                        }`}
                          >
                            <span className="block font-semibold truncate">
                              {formatTimeInZone(appointment.starts_at, zone)}{" "}
                              {appointment.customer_name}
                            </span>
                            {height > 34 && (
                              <span className="block truncate text-gray-500">
                                {appointment.service_name}
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Anything the grid could not place — never silently dropped. */}
      {unplaced.length > 0 && (
        <section className="mt-6">
          <h2 className="section-title mb-2">Not shown on the grid</h2>
          <p className="text-xs text-gray-400 mb-3">
            These have no resource at this branch, or fall outside{" "}
            {DAY_START_HOUR}:00–{DAY_END_HOUR}:00.
          </p>
          <div className="card overflow-hidden">
            <table className="data-table">
              <tbody>
                {unplaced.map((appointment) => (
                  <tr key={appointment.id}>
                    <td className="tabular-nums whitespace-nowrap">
                      {formatTimeInZone(appointment.starts_at, zone)}
                    </td>
                    <td className="font-medium text-gray-900">
                      {appointment.customer_name}
                    </td>
                    <td className="text-gray-600">{appointment.service_name}</td>
                    <td>
                      <span className={statusBadgeClass(appointment.status)}>
                        {statusLabel(appointment.status)}
                      </span>
                    </td>
                    <td className="text-right">
                      <button
                        className="btn-ghost btn-sm"
                        onClick={() => setSelected(appointment)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {selected && (
        <AppointmentDrawer
          appointment={selected}
          onChanged={replace}
          onClose={() => setSelected(null)}
        />
      )}

      {booking && (
        <BookAppointmentModal
          initialDate={date}
          onBooked={() => load()}
          onClose={() => setBooking(false)}
        />
      )}
    </div>
  );
}
