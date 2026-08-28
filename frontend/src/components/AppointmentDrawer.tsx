// One appointment, in full: details, lifecycle actions, and its audit trail.
//
// The action row is driven by the server's transition rules rather than a fixed
// set of buttons, so the drawer cannot offer "Complete" on a cancelled
// appointment. When the server rejects a move anyway (a 422), the reason is
// shown as-is — it is written for a human.
import { useEffect, useState } from "react";
import { Clock, MapPin, User, X } from "lucide-react";
import { ApiError } from "../api/client";
import {
  Appointment,
  AppointmentHistoryEntry,
  AppointmentStatus,
  appointmentsApi,
  formatDateInZone,
  formatInZone,
  formatTimeInZone,
  statusBadgeClass,
  statusLabel,
} from "../api/appointments";

/** Which moves the UI offers from each status.
 *
 *  A deliberate mirror of the domain's transition table, not a second source of
 *  truth: the server still validates, and an unlisted status simply offers
 *  Cancel. Keeping it here is what stops the drawer showing a button that is
 *  guaranteed to 422. */
const ACTIONS: Record<string, { label: string; target: AppointmentStatus }[]> = {
  draft: [{ label: "Confirm", target: "confirmed" }],
  requested: [{ label: "Confirm", target: "confirmed" }],
  pending: [{ label: "Confirm", target: "confirmed" }],
  awaiting_confirmation: [{ label: "Confirm", target: "confirmed" }],
  confirmed: [
    { label: "Check in", target: "checked_in" },
    { label: "No-show", target: "no_show" },
  ],
  arrived: [{ label: "Check in", target: "checked_in" }],
  checked_in: [{ label: "Start", target: "in_progress" }],
  in_progress: [{ label: "Complete", target: "completed" }],
  waitlisted: [{ label: "Confirm", target: "confirmed" }],
};

const CALLS: Record<string, (id: string, reason?: string) => Promise<Appointment>> = {
  confirmed: appointmentsApi.confirm,
  checked_in: appointmentsApi.checkIn,
  in_progress: appointmentsApi.start,
  completed: appointmentsApi.complete,
  cancelled: appointmentsApi.cancel,
  no_show: appointmentsApi.noShow,
};

const TERMINAL = new Set(["completed", "cancelled", "no_show", "rescheduled"]);

export default function AppointmentDrawer({
  appointment: initial,
  onChanged,
  onClose,
}: {
  appointment: Appointment;
  onChanged: (appointment: Appointment) => void;
  onClose: () => void;
}) {
  const [appointment, setAppointment] = useState(initial);
  const [history, setHistory] = useState<AppointmentHistoryEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAppointment(initial);
  }, [initial]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setHistory(null);
      try {
        const result = await appointmentsApi.history(appointment.id);
        if (!cancelled) setHistory(result.entries);
      } catch {
        // The timeline is supporting detail; failing to load it must not take
        // the drawer down. An empty list renders its own message.
        if (!cancelled) setHistory([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appointment.id]);

  async function act(target: AppointmentStatus, reason = "") {
    const call = CALLS[target];
    if (!call) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await call(appointment.id, reason);
      setAppointment(updated);
      onChanged(updated);
      const refreshed = await appointmentsApi.history(appointment.id);
      setHistory(refreshed.entries);
    } catch (err) {
      // 422 carries the domain's own explanation ("An appointment that is
      // cancelled cannot become completed"), which is better than anything
      // this component could write.
      setError(err instanceof ApiError ? err.message : "That action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    const reason = window.prompt("Why is this being cancelled? (optional)") ?? "";
    await act("cancelled", reason);
  }

  const zone = appointment.timezone;
  const available = ACTIONS[appointment.status] ?? [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Appointment details"
      className="drawer-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-chrome h-full w-full max-w-md overflow-y-auto border-l animate-slide-in-right">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b chrome-rule">
          <div>
            <h2 className="font-display text-[17px] font-semibold text-gray-900">
              {appointment.customer_name}
            </h2>
            <span className={`${statusBadgeClass(appointment.status)} mt-1.5`}>
              {statusLabel(appointment.status)}
            </span>
          </div>
          <button onClick={onClose} aria-label="Close" className="btn-ghost p-1.5 h-auto">
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <dl className="space-y-3 text-sm">
            <div className="flex items-start gap-2.5">
              <Clock className="w-4 h-4 text-gray-400 mt-0.5" strokeWidth={1.75} />
              <div>
                <dt className="sr-only">When</dt>
                <dd className="text-gray-900 font-medium">
                  {formatDateInZone(appointment.starts_at, zone)},{" "}
                  {formatTimeInZone(appointment.starts_at, zone)} –{" "}
                  {formatTimeInZone(appointment.ends_at, zone)}
                </dd>
                {/* The branch's clock, stated: a receptionist looking at another
                    branch must not read these as their own local times. */}
                <dd className="text-xs text-gray-400">{zone}</dd>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <MapPin className="w-4 h-4 text-gray-400 mt-0.5" strokeWidth={1.75} />
              <div>
                <dt className="sr-only">Where</dt>
                <dd className="text-gray-700">
                  {appointment.service_name || "Service"} ·{" "}
                  {appointment.location_name || "Location"}
                </dd>
                {appointment.resource_names.filter(Boolean).length > 0 && (
                  <dd className="text-xs text-gray-400">
                    with {appointment.resource_names.filter(Boolean).join(", ")}
                  </dd>
                )}
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <User className="w-4 h-4 text-gray-400 mt-0.5" strokeWidth={1.75} />
              <div>
                <dt className="sr-only">Customer</dt>
                <dd className="text-gray-700">
                  {appointment.customer_phone || appointment.customer_email || "—"}
                </dd>
                <dd className="text-xs text-gray-400">
                  Booked via {appointment.source.replace(/_/g, " ")}
                </dd>
              </div>
            </div>
          </dl>

          {appointment.customer_notes && (
            <div>
              <p className="eyebrow mb-1">Customer notes</p>
              <p className="text-sm text-gray-600">{appointment.customer_notes}</p>
            </div>
          )}

          {appointment.cancellation_reason && (
            <div>
              <p className="eyebrow mb-1">Cancellation reason</p>
              <p className="text-sm text-gray-600">{appointment.cancellation_reason}</p>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
            >
              {error}
            </div>
          )}

          {/* --- Actions --- */}
          {!TERMINAL.has(appointment.status) && (
            <div className="flex flex-wrap gap-2 border-t chrome-rule pt-4">
              {available.map((action) => (
                <button
                  key={action.target}
                  disabled={busy}
                  onClick={() => act(action.target)}
                  className="btn-secondary btn-sm"
                >
                  {action.label}
                </button>
              ))}
              <button disabled={busy} onClick={cancel} className="btn-ghost btn-sm text-red-500">
                Cancel appointment
              </button>
            </div>
          )}

          {/* --- Audit trail (spec section 40) --- */}
          <div className="border-t chrome-rule pt-4">
            <p className="eyebrow mb-3">History</p>
            {history === null ? (
              <div className="space-y-2" aria-busy="true">
                {[0, 1].map((i) => (
                  <div key={i} className="skeleton h-8 w-full" />
                ))}
              </div>
            ) : history.length === 0 ? (
              <p className="text-sm text-gray-400">No history recorded.</p>
            ) : (
              <ol className="space-y-3">
                {history.map((entry, index) => (
                  <li key={index} className="flex gap-3 text-sm">
                    <div className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-brand-500" />
                    <div>
                      <p className="text-gray-700">
                        {entry.from_status
                          ? `${statusLabel(entry.from_status)} → ${statusLabel(entry.to_status)}`
                          : `Created as ${statusLabel(entry.to_status)}`}
                      </p>
                      <p className="text-xs text-gray-400">
                        {entry.actor_label || entry.actor_kind.replace(/_/g, " ")}
                        {entry.channel && ` · ${entry.channel}`} ·{" "}
                        {formatInZone(entry.occurred_at, zone, {
                          day: "numeric",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </p>
                      {entry.reason && (
                        <p className="text-xs text-gray-500 mt-0.5">{entry.reason}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
