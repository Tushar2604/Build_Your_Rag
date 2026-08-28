// Resources: staff, rooms, equipment, vehicles (spec section 10).
//
// One page for all of them, because the scheduler treats them identically — a
// treatment room is booked exactly the way a dentist is. Separating "staff" into
// its own screen is what makes a product unable to book a meeting room later.
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Armchair,
  Car,
  Plus,
  User,
  Users2,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { ApiError } from "../api/client";
import {
  Location,
  Resource,
  ResourceKind,
  locationsApi,
  resourcesApi,
} from "../api/appointments";

const KIND_META: Record<ResourceKind, { label: string; icon: LucideIcon; hint: string }> = {
  staff: { label: "Staff", icon: User, hint: "A person who serves customers" },
  room: { label: "Room", icon: Armchair, hint: "A treatment or meeting room" },
  equipment: { label: "Equipment", icon: Wrench, hint: "A machine or device" },
  vehicle: { label: "Vehicle", icon: Car, hint: "A car, van, or bike" },
  other: { label: "Other", icon: Users2, hint: "Anything else a booking needs" },
};

const KINDS = Object.keys(KIND_META) as ResourceKind[];

function ResourceModal({
  editing,
  locations,
  onSaved,
  onClose,
}: {
  editing: Resource | null;
  locations: Location[];
  onSaved: (resource: Resource) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    name: editing?.name ?? "",
    kind: (editing?.kind ?? "staff") as ResourceKind,
    location_id: editing?.location_id ?? "",
    email: editing?.email ?? "",
    phone: editing?.phone ?? "",
    capacity: editing?.capacity ?? 1,
    is_active: editing?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body = { ...form, location_id: form.location_id || null };
      const saved = editing
        ? await resourcesApi.update(editing.id, body)
        : await resourcesApi.create(body);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this resource.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={editing ? "Edit resource" : "Add resource"}
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        onSubmit={handleSave}
        className="card shadow-modal w-full max-w-lg max-h-[90vh] overflow-y-auto animate-scale-in"
      >
        <div className="px-6 py-4 border-b chrome-rule">
          <h2 className="text-sm font-semibold text-gray-900">
            {editing ? "Edit resource" : "Add a resource"}
          </h2>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="label" htmlFor="res-name">
              Name *
            </label>
            <input
              id="res-name"
              required
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Dr Khan, or Treatment Room 2"
            />
          </div>

          <fieldset>
            <legend className="label">Type *</legend>
            <div className="grid grid-cols-5 gap-2">
              {KINDS.map((kind) => {
                const { label, icon: Icon } = KIND_META[kind];
                const selected = form.kind === kind;
                return (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setForm({ ...form, kind })}
                    className={`flex flex-col items-center gap-1.5 rounded-xl border px-2 py-3 text-[11px]
                                font-semibold transition-colors ${
                                  selected
                                    ? "border-brand-400 bg-brand-500/10 text-brand-700"
                                    : "chrome-rule text-gray-500 hover:text-gray-800"
                                }`}
                  >
                    <Icon className="w-4 h-4" strokeWidth={1.75} />
                    {label}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">{KIND_META[form.kind].hint}</p>
          </fieldset>

          <div>
            <label className="label" htmlFor="res-location">
              Location
            </label>
            <select
              id="res-location"
              className="input"
              value={form.location_id ?? ""}
              onChange={(e) => setForm({ ...form, location_id: e.target.value })}
            >
              <option value="">Every location</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Leave as "every location" for someone or something that moves
              between branches.
            </p>
          </div>

          {form.kind === "staff" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="res-email">
                  Email
                </label>
                <input
                  id="res-email"
                  type="email"
                  className="input"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="res-phone">
                  Phone
                </label>
                <input
                  id="res-phone"
                  className="input"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            Available for booking
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
            {saving ? "Saving…" : editing ? "Save changes" : "Add resource"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function ResourcesPage() {
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [locations, setLocations] = useState<Location[]>([]);
  const [filter, setFilter] = useState<ResourceKind | "">("");
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ open: boolean; editing: Resource | null }>({
    open: false,
    editing: null,
  });

  async function load() {
    setError(null);
    try {
      const [list, locs] = await Promise.all([
        resourcesApi.list(),
        locationsApi.list(),
      ]);
      setResources(list);
      setLocations(locs);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load resources.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  function upsert(saved: Resource) {
    setResources((current) => {
      if (!current) return [saved];
      const index = current.findIndex((r) => r.id === saved.id);
      if (index === -1) return [...current, saved];
      const next = [...current];
      next[index] = saved;
      return next;
    });
  }

  const shown = resources?.filter((r) => !filter || r.kind === filter) ?? null;
  const locationName = (id: string | null) =>
    id ? locations.find((l) => l.id === id)?.name ?? "—" : "Every location";

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Resources</h1>
          <p className="page-subtitle">
            Everyone and everything a booking consumes — staff, rooms,
            equipment. A service can require several at once.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn-primary"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add resource
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

      {resources && resources.length > 0 && (
        <div className="segmented mb-5">
          <button
            className={filter === "" ? "segmented-item-active" : "segmented-item"}
            onClick={() => setFilter("")}
          >
            All
          </button>
          {KINDS.map((kind) => (
            <button
              key={kind}
              className={filter === kind ? "segmented-item-active" : "segmented-item"}
              onClick={() => setFilter(kind)}
            >
              {KIND_META[kind].label}
            </button>
          ))}
        </div>
      )}

      {resources === null && !error && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading resources">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-16 w-full" />
          ))}
        </div>
      )}

      {resources?.length === 0 && (
        <div className="empty-state">
          <Users2 className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">No resources yet</p>
          <p className="empty-state-desc">
            Add the people and rooms that appointments consume. A service becomes
            bookable once at least one eligible resource exists.
          </p>
          <button
            className="btn-primary mt-5"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add your first resource
          </button>
        </div>
      )}

      {shown && shown.length === 0 && (resources?.length ?? 0) > 0 && (
        <div className="empty-state">
          <p className="empty-state-title">Nothing of that type</p>
          <p className="empty-state-desc">
            No {KIND_META[filter as ResourceKind]?.label.toLowerCase()} resources
            have been added yet.
          </p>
        </div>
      )}

      {shown && shown.length > 0 && (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Location</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((resource) => {
                const { label, icon: Icon } = KIND_META[resource.kind] ?? KIND_META.other;
                return (
                  <tr key={resource.id}>
                    <td>
                      <div className="font-medium text-gray-900">{resource.name}</div>
                      {resource.email && (
                        <div className="text-xs text-gray-400 mt-0.5">
                          {resource.email}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="inline-flex items-center gap-1.5 text-gray-600">
                        <Icon className="w-3.5 h-3.5 text-gray-400" strokeWidth={1.75} />
                        {label}
                      </span>
                    </td>
                    <td className="text-gray-600">
                      {locationName(resource.location_id)}
                    </td>
                    <td>
                      <span
                        className={resource.is_active ? "badge-live" : "badge-neutral"}
                      >
                        {resource.is_active ? "Bookable" : "Inactive"}
                      </span>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <Link
                        to={`/appointments/availability?owner=${resource.id}&kind=resource`}
                        className="btn-ghost btn-sm"
                      >
                        Hours
                      </Link>
                      <button
                        className="btn-ghost btn-sm"
                        onClick={() => setModal({ open: true, editing: resource })}
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modal.open && (
        <ResourceModal
          editing={modal.editing}
          locations={locations}
          onSaved={upsert}
          onClose={() => setModal({ open: false, editing: null })}
        />
      )}
    </div>
  );
}
