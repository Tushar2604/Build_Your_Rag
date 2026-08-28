// Branches: where appointments happen (spec section 34).
//
// A location's timezone is the single most consequential field in the module —
// every weekly availability rule underneath it is resolved against it — so the
// form says so rather than presenting it as one field among several.
import { FormEvent, useEffect, useState } from "react";
import { MapPin, Plus, Clock } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { Location, locationsApi } from "../api/appointments";

// A short, curated list plus whatever the browser reports. Every IANA zone
// would be a 400-item dropdown; these cover the deployments this product has,
// and the browser's own zone is always offered so a new market is never blocked.
const COMMON_TIMEZONES = [
  "UTC",
  "Asia/Dubai",
  "Asia/Riyadh",
  "Asia/Karachi",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Australia/Sydney",
];

function timezoneOptions(): string[] {
  const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return local && !COMMON_TIMEZONES.includes(local)
    ? [local, ...COMMON_TIMEZONES]
    : COMMON_TIMEZONES;
}

const EMPTY = {
  name: "",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  address: "",
  phone: "",
  email: "",
  is_active: true,
};

function LocationModal({
  editing,
  onSaved,
  onClose,
}: {
  editing: Location | null;
  onSaved: (location: Location) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState(
    editing
      ? {
          name: editing.name,
          timezone: editing.timezone,
          address: editing.address,
          phone: editing.phone,
          email: editing.email,
          is_active: editing.is_active,
        }
      : EMPTY,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = editing
        ? await locationsApi.update(editing.id, form)
        : await locationsApi.create(form);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save this location.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={editing ? "Edit location" : "Add location"}
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        onSubmit={handleSave}
        className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in"
      >
        <div className="px-6 py-4 border-b chrome-rule">
          <h2 className="text-sm font-semibold text-gray-900">
            {editing ? "Edit location" : "Add a location"}
          </h2>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="label" htmlFor="loc-name">
              Name *
            </label>
            <input
              id="loc-name"
              required
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Dubai Marina Clinic"
            />
          </div>

          <div>
            <label className="label" htmlFor="loc-tz">
              Timezone *
            </label>
            <select
              id="loc-tz"
              className="input"
              value={form.timezone}
              onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            >
              {timezoneOptions().map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Opening hours are stored in this branch's local time, so they stay
              correct through daylight-saving changes.
            </p>
          </div>

          <div>
            <label className="label" htmlFor="loc-address">
              Address
            </label>
            <textarea
              id="loc-address"
              rows={2}
              className="input"
              value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label" htmlFor="loc-phone">
                Phone
              </label>
              <input
                id="loc-phone"
                className="input"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+971 4 000 0000"
              />
            </div>
            <div>
              <label className="label" htmlFor="loc-email">
                Email
              </label>
              <input
                id="loc-email"
                type="email"
                className="input"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            Accepting bookings
          </label>

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
          <button type="submit" disabled={saving || !form.name} className="btn-primary">
            {saving ? "Saving…" : editing ? "Save changes" : "Add location"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function LocationsPage() {
  const [locations, setLocations] = useState<Location[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ open: boolean; editing: Location | null }>({
    open: false,
    editing: null,
  });

  async function load() {
    setError(null);
    try {
      setLocations(await locationsApi.list());
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load locations.",
      );
    }
  }

  useEffect(() => {
    load();
  }, []);

  function upsert(saved: Location) {
    setLocations((current) => {
      if (!current) return [saved];
      const index = current.findIndex((l) => l.id === saved.id);
      if (index === -1) return [...current, saved];
      const next = [...current];
      next[index] = saved;
      return next;
    });
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Locations</h1>
          <p className="page-subtitle">
            Your branches. Each one keeps its own timezone, opening hours, and
            staff.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn-primary"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add location
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

      {locations === null && !error && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading locations">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-16 w-full" />
          ))}
        </div>
      )}

      {locations?.length === 0 && (
        <div className="empty-state">
          <MapPin className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">No locations yet</p>
          <p className="empty-state-desc">
            Add the branch where you see customers. Everything else —
            services, staff, opening hours — hangs off a location.
          </p>
          <button
            className="btn-primary mt-5"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add your first location
          </button>
        </div>
      )}

      {locations && locations.length > 0 && (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Timezone</th>
                <th scope="col">Contact</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {locations.map((location) => (
                <tr key={location.id}>
                  <td>
                    <div className="font-medium text-gray-900">{location.name}</div>
                    {location.address && (
                      <div className="text-xs text-gray-400 mt-0.5">
                        {location.address}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-1.5 text-gray-600">
                      <Clock className="w-3.5 h-3.5 text-gray-400" strokeWidth={1.75} />
                      {location.timezone}
                    </span>
                  </td>
                  <td className="text-gray-600">
                    {location.phone || location.email || "—"}
                  </td>
                  <td>
                    <span
                      className={location.is_active ? "badge-live" : "badge-neutral"}
                    >
                      {location.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <Link
                      to={`/appointments/availability?owner=${location.id}&kind=location`}
                      className="btn-ghost btn-sm"
                    >
                      Hours
                    </Link>
                    <button
                      className="btn-ghost btn-sm"
                      onClick={() => setModal({ open: true, editing: location })}
                    >
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal.open && (
        <LocationModal
          editing={modal.editing}
          onSaved={upsert}
          onClose={() => setModal({ open: false, editing: null })}
        />
      )}
    </div>
  );
}
