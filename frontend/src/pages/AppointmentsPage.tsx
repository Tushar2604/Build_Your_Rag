// The appointment list: search, filter, and today's numbers.
//
// Complements the calendar rather than duplicating it. The calendar answers
// "what does this day look like"; this answers "find me that booking" and
// "how are we doing" — which are different questions and want different shapes.
import { useEffect, useState } from "react";
import { CalendarCheck, Plus, Search } from "lucide-react";
import { ApiError } from "../api/client";
import AppointmentDrawer from "../components/AppointmentDrawer";
import BookAppointmentModal from "../components/BookAppointmentModal";
import {
  Appointment,
  AppointmentSummary,
  appointmentsApi,
  formatDateInZone,
  formatTimeInZone,
  statusBadgeClass,
  statusLabel,
} from "../api/appointments";

const PAGE_SIZE = 50;

// The filters a front desk actually reaches for, in the order they reach for
// them. Not every status — thirteen chips would be a wall.
const FILTERS: { label: string; statuses: string }[] = [
  { label: "All", statuses: "" },
  { label: "Needs confirming", statuses: "pending,requested,awaiting_confirmation" },
  { label: "Confirmed", statuses: "confirmed" },
  { label: "In the building", statuses: "arrived,checked_in,in_progress" },
  { label: "Completed", statuses: "completed" },
  { label: "Cancelled", statuses: "cancelled,no_show" },
];

/** Today, as the UTC instants the API filters on. */
function todayBounds(): { start: string; end: string } {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start: start.toISOString(), end: end.toISOString() };
}

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<Appointment[] | null>(null);
  const [summary, setSummary] = useState<AppointmentSummary | null>(null);
  const [filter, setFilter] = useState(0);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [booking, setBooking] = useState(false);

  async function load() {
    setError(null);
    setAppointments(null);
    try {
      const result = await appointmentsApi.list({
        status: FILTERS[filter].statuses,
        search,
        page,
        page_size: PAGE_SIZE,
      });
      setAppointments(result.appointments);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load appointments.");
      setAppointments([]);
    }
  }

  async function loadSummary() {
    try {
      const { start, end } = todayBounds();
      setSummary(await appointmentsApi.summary(start, end));
    } catch {
      // The tiles are a nicety; the list is the page. Failing to count must not
      // stop someone finding a booking.
      setSummary(null);
    }
  }

  // Debounced so typing a name is not one request per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, search, page]);

  useEffect(() => {
    loadSummary();
  }, []);

  function replace(updated: Appointment) {
    setAppointments((current) =>
      (current ?? []).map((a) => (a.id === updated.id ? updated : a)),
    );
    setSelected(updated);
    loadSummary();
  }

  const tiles = summary
    ? [
        { label: "Today", value: summary.total },
        { label: "Confirmed", value: summary.by_status.confirmed ?? 0 },
        {
          label: "Awaiting",
          value:
            (summary.by_status.pending ?? 0) +
            (summary.by_status.requested ?? 0) +
            (summary.by_status.awaiting_confirmation ?? 0),
        },
        { label: "Completed", value: summary.by_status.completed ?? 0 },
        { label: "No-shows", value: summary.by_status.no_show ?? 0 },
      ]
    : [];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Appointments</h1>
          <p className="page-subtitle">Every booking, however it was made.</p>
        </div>
        <div className="page-header-actions">
          <button className="btn-primary" onClick={() => setBooking(true)}>
            <Plus className="w-4 h-4" strokeWidth={2} />
            New appointment
          </button>
        </div>
      </div>

      {tiles.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5 mb-6">
          {tiles.map((tile) => (
            <div key={tile.label} className="metric-card">
              <p className="metric-card-label">{tile.label}</p>
              <p className="metric-card-value">{tile.value}</p>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="segmented">
          {FILTERS.map((entry, index) => (
            <button
              key={entry.label}
              className={index === filter ? "segmented-item-active" : "segmented-item"}
              onClick={() => {
                setFilter(index);
                setPage(1);
              }}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 w-4 h-4 -translate-y-1/2 text-gray-400"
            strokeWidth={1.75}
          />
          <input
            className="input pl-9"
            placeholder="Name, phone or email…"
            aria-label="Search appointments"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
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

      {appointments === null && !error && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading appointments">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton h-14 w-full" />
          ))}
        </div>
      )}

      {appointments?.length === 0 && (
        <div className="empty-state">
          <CalendarCheck className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">
            {search || filter > 0 ? "Nothing matches" : "No appointments yet"}
          </p>
          <p className="empty-state-desc">
            {search || filter > 0
              ? "Try a different filter or search term."
              : "Once a location, a service and a resource exist, bookings will appear here — whether made here, by an agent, or through the API."}
          </p>
          {!search && filter === 0 && (
            <button className="btn-primary mt-5" onClick={() => setBooking(true)}>
              <Plus className="w-4 h-4" strokeWidth={2} />
              Book an appointment
            </button>
          )}
        </div>
      )}

      {appointments && appointments.length > 0 && (
        <>
          <div className="card overflow-hidden">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Customer</th>
                  <th scope="col">Service</th>
                  <th scope="col">With</th>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map((appointment) => (
                  <tr
                    key={appointment.id}
                    onClick={() => setSelected(appointment)}
                    className="cursor-pointer"
                  >
                    <td className="whitespace-nowrap">
                      <div className="font-medium text-gray-900">
                        {formatDateInZone(appointment.starts_at, appointment.timezone)}
                      </div>
                      <div className="text-xs text-gray-400 tabular-nums">
                        {formatTimeInZone(appointment.starts_at, appointment.timezone)}
                      </div>
                    </td>
                    <td>
                      <div className="font-medium text-gray-900">
                        {appointment.customer_name}
                      </div>
                      <div className="text-xs text-gray-400">
                        {appointment.customer_phone || appointment.customer_email}
                      </div>
                    </td>
                    <td className="text-gray-600">{appointment.service_name}</td>
                    <td className="text-gray-600">
                      {appointment.resource_names.filter(Boolean).join(", ") || "—"}
                    </td>
                    <td className="text-gray-500 text-xs">
                      {appointment.source.replace(/_/g, " ")}
                    </td>
                    <td>
                      <span className={statusBadgeClass(appointment.status)}>
                        {statusLabel(appointment.status)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <p className="text-xs text-gray-400">
              Showing {appointments.length} appointment
              {appointments.length === 1 ? "" : "s"}
            </p>
            <div className="flex gap-2">
              <button
                className="btn-secondary btn-sm"
                disabled={page === 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </button>
              <button
                className="btn-secondary btn-sm"
                // A full page means there is probably another; a short one is
                // definitely the last. Cheaper than counting on every keystroke.
                disabled={appointments.length < PAGE_SIZE}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
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
          onBooked={() => {
            load();
            loadSummary();
          }}
          onClose={() => setBooking(false)}
        />
      )}
    </div>
  );
}
