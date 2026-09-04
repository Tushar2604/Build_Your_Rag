// Services: what customers book (spec section 9).
//
// The eligibility editor is the part worth care. A service names the resources
// that can serve it AND the role each fills, which is what makes "a dentist and
// a chair" expressible — the availability engine fills every distinct required
// role before it will offer a slot. Getting that wrong is the difference between
// a bookable service and one that silently never has availability.
import { FormEvent, useEffect, useState } from "react";
import { Briefcase, Plus, AlertTriangle } from "lucide-react";
import { ApiError } from "../api/client";
import {
  Resource,
  Service,
  ServiceResourceLink,
  money,
  resourcesApi,
  servicesApi,
} from "../api/appointments";

// Progressive disclosure: name and duration are all most services need, and the
// booking rules are hidden until someone asks for them.
function ServiceModal({
  editing,
  resources,
  onSaved,
  onClose,
}: {
  editing: Service | null;
  resources: Resource[];
  onSaved: (service: Service) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
    name: editing?.name ?? "",
    category: editing?.category ?? "",
    description: editing?.description ?? "",
    duration_minutes: editing?.duration_minutes ?? 30,
    buffer_before_minutes: editing?.buffer_before_minutes ?? 0,
    buffer_after_minutes: editing?.buffer_after_minutes ?? 0,
    price_cents: editing?.price_cents ?? 0,
    deposit_cents: editing?.deposit_cents ?? 0,
    currency: editing?.currency ?? "AED",
    min_notice_minutes: editing?.min_notice_minutes ?? 0,
    max_horizon_days: editing?.max_horizon_days ?? 60,
    cancellation_window_hours: editing?.cancellation_window_hours ?? 0,
    online_bookable: editing?.online_bookable ?? true,
    is_active: editing?.is_active ?? true,
  });
  const [links, setLinks] = useState<ServiceResourceLink[]>(editing?.resources ?? []);
  const [showRules, setShowRules] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleResource(resourceId: string) {
    setLinks((current) =>
      current.some((l) => l.resource_id === resourceId)
        ? current.filter((l) => l.resource_id !== resourceId)
        : [...current, { resource_id: resourceId, role: "primary", required: true }],
    );
  }

  function setRole(resourceId: string, role: string) {
    setLinks((current) =>
      current.map((l) => (l.resource_id === resourceId ? { ...l, role } : l)),
    );
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const saved = editing
        ? await servicesApi.update(editing.id, form)
        : await servicesApi.create(form);
      // Eligibility is a separate call because it is a separate resource; the
      // service exists either way, so a failure here leaves a usable service
      // rather than nothing.
      const withResources = await servicesApi.setResources(saved.id, links);
      onSaved(withResources);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this service.");
    } finally {
      setSaving(false);
    }
  }

  const roles = [...new Set(links.map((l) => l.role))];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={editing ? "Edit service" : "Add service"}
      className="modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <form
        onSubmit={handleSave}
        className="card shadow-modal w-full max-w-xl max-h-[90vh] overflow-y-auto animate-scale-in"
      >
        <div className="px-6 py-4 border-b chrome-rule">
          <h2 className="text-sm font-semibold text-gray-900">
            {editing ? "Edit service" : "Add a service"}
          </h2>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="label" htmlFor="svc-name">
                Name *
              </label>
              <input
                id="svc-name"
                required
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Dental consultation"
              />
            </div>
            <div>
              <label className="label" htmlFor="svc-duration">
                Minutes *
              </label>
              <input
                id="svc-duration"
                type="number"
                min={1}
                max={1440}
                required
                className="input"
                value={form.duration_minutes}
                onChange={(e) =>
                  setForm({ ...form, duration_minutes: Number(e.target.value) })
                }
              />
            </div>
          </div>

          <div>
            <label className="label" htmlFor="svc-category">
              Category
            </label>
            <input
              id="svc-category"
              className="input"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              placeholder="General dentistry"
            />
          </div>

          {/* --- Eligibility --- */}
          <fieldset>
            <legend className="label">Who and what this needs *</legend>
            {resources.length === 0 ? (
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
                <AlertTriangle className="w-4 h-4 inline mr-1.5 -mt-0.5" strokeWidth={2} />
                No resources exist yet. A service with no eligible resource can
                never be booked — add staff or a room first.
              </div>
            ) : (
              <>
                <div className="max-h-56 overflow-y-auto rounded-xl border chrome-rule divide-y divide-gray-100">
                  {resources.map((resource) => {
                    const link = links.find((l) => l.resource_id === resource.id);
                    return (
                      <div
                        key={resource.id}
                        className="flex items-center gap-3 px-3 py-2"
                      >
                        <input
                          type="checkbox"
                          id={`res-${resource.id}`}
                          checked={!!link}
                          onChange={() => toggleResource(resource.id)}
                        />
                        <label
                          htmlFor={`res-${resource.id}`}
                          className="flex-1 text-sm text-gray-700 cursor-pointer"
                        >
                          {resource.name}
                          <span className="text-gray-400 text-xs ml-1.5">
                            {resource.kind}
                          </span>
                        </label>
                        {link && (
                          <input
                            aria-label={`Role for ${resource.name}`}
                            className="input w-32 py-1 text-xs"
                            value={link.role}
                            onChange={(e) => setRole(resource.id, e.target.value)}
                            placeholder="role"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-gray-400 mt-1.5">
                  {roles.length > 1 ? (
                    <>
                      This service needs <strong>one of each role</strong> free at
                      the same time: {roles.join(", ")}.
                    </>
                  ) : (
                    <>
                      Resources sharing a role are alternatives — any one free is
                      enough. Give a room a different role (e.g. "room") to
                      require a practitioner <em>and</em> a room together.
                    </>
                  )}
                </p>
              </>
            )}
          </fieldset>

          <button
            type="button"
            onClick={() => setShowRules((s) => !s)}
            className="btn-ghost btn-sm px-0"
            aria-expanded={showRules}
          >
            {showRules ? "Hide" : "Show"} booking rules, buffers and pricing
          </button>

          {showRules && (
            <div className="space-y-4 rounded-xl border chrome-rule p-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label" htmlFor="svc-buffer-before">
                    Buffer before (min)
                  </label>
                  <input
                    id="svc-buffer-before"
                    type="number"
                    min={0}
                    className="input"
                    value={form.buffer_before_minutes}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        buffer_before_minutes: Number(e.target.value),
                      })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="svc-buffer-after">
                    Buffer after (min)
                  </label>
                  <input
                    id="svc-buffer-after"
                    type="number"
                    min={0}
                    className="input"
                    value={form.buffer_after_minutes}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        buffer_after_minutes: Number(e.target.value),
                      })
                    }
                  />
                </div>
              </div>
              <p className="text-xs text-gray-400 -mt-2">
                Buffers block the calendar without lengthening the customer's
                appointment.
              </p>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="label" htmlFor="svc-price">
                    Price
                  </label>
                  <input
                    id="svc-price"
                    type="number"
                    min={0}
                    step="0.01"
                    className="input"
                    value={form.price_cents / 100}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        price_cents: Math.round(Number(e.target.value) * 100),
                      })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="svc-deposit">
                    Deposit
                  </label>
                  <input
                    id="svc-deposit"
                    type="number"
                    min={0}
                    step="0.01"
                    className="input"
                    value={form.deposit_cents / 100}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        deposit_cents: Math.round(Number(e.target.value) * 100),
                      })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="svc-currency">
                    Currency
                  </label>
                  <input
                    id="svc-currency"
                    maxLength={3}
                    className="input uppercase"
                    value={form.currency}
                    onChange={(e) => setForm({ ...form, currency: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="label" htmlFor="svc-notice">
                    Min notice (min)
                  </label>
                  <input
                    id="svc-notice"
                    type="number"
                    min={0}
                    className="input"
                    value={form.min_notice_minutes}
                    onChange={(e) =>
                      setForm({ ...form, min_notice_minutes: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="svc-horizon">
                    Book up to (days)
                  </label>
                  <input
                    id="svc-horizon"
                    type="number"
                    min={1}
                    className="input"
                    value={form.max_horizon_days}
                    onChange={(e) =>
                      setForm({ ...form, max_horizon_days: Number(e.target.value) })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="svc-cancel">
                    Cancel window (hrs)
                  </label>
                  <input
                    id="svc-cancel"
                    type="number"
                    min={0}
                    className="input"
                    value={form.cancellation_window_hours}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        cancellation_window_hours: Number(e.target.value),
                      })
                    }
                  />
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={form.online_bookable}
                  onChange={(e) =>
                    setForm({ ...form, online_bookable: e.target.checked })
                  }
                />
                Customers can book this themselves
              </label>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            Active
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
            {saving ? "Saving…" : editing ? "Save changes" : "Add service"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function ServicesPage() {
  const [services, setServices] = useState<Service[] | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<{ open: boolean; editing: Service | null }>({
    open: false,
    editing: null,
  });

  async function load() {
    setError(null);
    try {
      const [list, res] = await Promise.all([
        servicesApi.list(),
        resourcesApi.list({ activeOnly: true }),
      ]);
      setServices(list);
      setResources(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load services.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  function upsert(saved: Service) {
    setServices((current) => {
      if (!current) return [saved];
      const index = current.findIndex((s) => s.id === saved.id);
      if (index === -1) return [...current, saved];
      const next = [...current];
      next[index] = saved;
      return next;
    });
  }

  return (
    <div className="page">
      <div className="page-header" data-tour="appointments-setup">
        <div>
          <h1 className="page-title">Services</h1>
          <p className="page-subtitle">
            What customers book, how long it takes, and what it needs to happen.
          </p>
        </div>
        <div className="page-header-actions">
          <button
            className="btn-primary"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add service
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

      {services === null && !error && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading services">
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton h-16 w-full" />
          ))}
        </div>
      )}

      {services?.length === 0 && (
        <div className="empty-state">
          <Briefcase className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">No services yet</p>
          <p className="empty-state-desc">
            A service is one bookable thing — a consultation, a haircut, a
            viewing. Add one and pick who can deliver it.
          </p>
          <button
            className="btn-primary mt-5"
            onClick={() => setModal({ open: true, editing: null })}
          >
            <Plus className="w-4 h-4" strokeWidth={2} />
            Add your first service
          </button>
        </div>
      )}

      {services && services.length > 0 && (
        <div className="card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col">Duration</th>
                <th scope="col">Price</th>
                <th scope="col">Resources</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {services.map((service) => {
                const bufferTotal =
                  service.buffer_before_minutes + service.buffer_after_minutes;
                return (
                  <tr key={service.id}>
                    <td>
                      <div className="font-medium text-gray-900">{service.name}</div>
                      {service.category && (
                        <div className="text-xs text-gray-400 mt-0.5">
                          {service.category}
                        </div>
                      )}
                    </td>
                    <td className="text-gray-600 whitespace-nowrap">
                      {service.duration_minutes} min
                      {bufferTotal > 0 && (
                        <span className="text-xs text-gray-400"> +{bufferTotal} buffer</span>
                      )}
                    </td>
                    <td className="text-gray-600 whitespace-nowrap">
                      {service.price_cents
                        ? money(service.price_cents, service.currency)
                        : "—"}
                    </td>
                    <td>
                      {service.resources.length === 0 ? (
                        // Not decoration: a service with no eligible resource
                        // can never produce a slot, and silence about it is how
                        // an operator concludes the calendar is broken.
                        <span className="badge-error">Not bookable</span>
                      ) : (
                        <span className="text-gray-600 text-xs">
                          {service.resources.length} assigned
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={service.is_active ? "badge-live" : "badge-neutral"}>
                        {service.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="text-right">
                      <button
                        className="btn-ghost btn-sm"
                        onClick={() => setModal({ open: true, editing: service })}
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
        <ServiceModal
          editing={modal.editing}
          resources={resources}
          onSaved={upsert}
          onClose={() => setModal({ open: false, editing: null })}
        />
      )}
    </div>
  );
}
