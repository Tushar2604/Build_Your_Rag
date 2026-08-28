// Opening hours and closures for one location or one resource (spec section 11).
//
// The two halves are deliberately different shapes, and the page says so:
// weekly rules are LOCAL wall-clock ("Mondays 09:00"), so they survive a
// daylight-saving change; blocks are absolute instants, because "that Tuesday
// off" really is one specific span of time.
import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarOff, Clock, Plus, Trash2 } from "lucide-react";
import { ApiError } from "../api/client";
import {
  AvailabilityRule,
  BlockedPeriod,
  Location,
  OwnerKind,
  Resource,
  WEEKDAY_LABELS,
  availabilityApi,
  locationsApi,
  resourcesApi,
} from "../api/appointments";

/** "09:00:00" or "09:00" from the API, always "09:00" for an <input type=time>. */
function toInputTime(value: string): string {
  return value.slice(0, 5);
}

export default function AvailabilityPage() {
  const [params, setParams] = useSearchParams();
  const ownerId = params.get("owner") ?? "";
  const ownerKind = (params.get("kind") as OwnerKind) || "location";

  const [locations, setLocations] = useState<Location[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [rules, setRules] = useState<AvailabilityRule[] | null>(null);
  const [blocks, setBlocks] = useState<BlockedPeriod[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [ruleForm, setRuleForm] = useState({
    weekday: 0,
    start_time: "09:00",
    end_time: "17:00",
  });
  const [blockForm, setBlockForm] = useState({
    starts_at: "",
    ends_at: "",
    reason: "",
  });

  useEffect(() => {
    (async () => {
      try {
        const [locs, res] = await Promise.all([
          locationsApi.list(),
          resourcesApi.list(),
        ]);
        setLocations(locs);
        setResources(res);
        // Land on the first location rather than an empty page when arriving
        // without a target.
        if (!ownerId && locs.length > 0) {
          setParams({ owner: locs[0].id, kind: "location" }, { replace: true });
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load owners.");
      }
    })();
    // Runs once: the owner pickers do not change while the page is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadSchedule() {
    if (!ownerId) return;
    setError(null);
    setRules(null);
    setBlocks(null);
    try {
      const [r, b] = await Promise.all([
        availabilityApi.listRules(ownerId),
        availabilityApi.listBlocks(ownerId),
      ]);
      setRules(r);
      setBlocks(b);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the schedule.");
    }
  }

  useEffect(() => {
    loadSchedule();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownerId]);

  const owner =
    ownerKind === "location"
      ? locations.find((l) => l.id === ownerId)
      : resources.find((r) => r.id === ownerId);

  // Which clock these wall-clock times are read against. A resource with no zone
  // of its own inherits its branch's, which is the usual setup.
  const zone =
    ownerKind === "location"
      ? (owner as Location | undefined)?.timezone
      : (owner as Resource | undefined)?.timezone ||
        locations.find((l) => l.id === (owner as Resource | undefined)?.location_id)
          ?.timezone;

  async function addRule(e: FormEvent) {
    e.preventDefault();
    if (!ownerId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await availabilityApi.createRule({
        owner_kind: ownerKind,
        owner_id: ownerId,
        weekday: ruleForm.weekday,
        start_time: ruleForm.start_time,
        end_time: ruleForm.end_time,
      });
      setRules((current) => [...(current ?? []), created]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add those hours.");
    } finally {
      setBusy(false);
    }
  }

  async function removeRule(id: string) {
    setError(null);
    try {
      await availabilityApi.deleteRule(id);
      setRules((current) => (current ?? []).filter((r) => r.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove those hours.");
    }
  }

  async function addBlock(e: FormEvent) {
    e.preventDefault();
    if (!ownerId || !blockForm.starts_at || !blockForm.ends_at) return;
    setBusy(true);
    setError(null);
    try {
      const created = await availabilityApi.createBlock({
        owner_kind: ownerKind,
        owner_id: ownerId,
        // `datetime-local` gives a naive local string; the Date round-trip is
        // what turns it into the UTC instant the API stores.
        starts_at: new Date(blockForm.starts_at).toISOString(),
        ends_at: new Date(blockForm.ends_at).toISOString(),
        reason: blockForm.reason,
      });
      setBlocks((current) => [...(current ?? []), created]);
      setBlockForm({ starts_at: "", ends_at: "", reason: "" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add that closure.");
    } finally {
      setBusy(false);
    }
  }

  async function removeBlock(id: string) {
    setError(null);
    try {
      await availabilityApi.deleteBlock(id);
      setBlocks((current) => (current ?? []).filter((b) => b.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that closure.");
    }
  }

  const byWeekday = (rules ?? []).reduce<Record<number, AvailabilityRule[]>>(
    (acc, rule) => {
      (acc[rule.weekday] ??= []).push(rule);
      return acc;
    },
    {},
  );

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Availability</h1>
          <p className="page-subtitle">
            When this branch is open, and when it is not.
          </p>
        </div>
      </div>

      {/* Owner picker */}
      <div className="card p-4 mb-6">
        <label className="label" htmlFor="owner-picker">
          Set hours for
        </label>
        <select
          id="owner-picker"
          className="input max-w-md"
          value={`${ownerKind}:${ownerId}`}
          onChange={(e) => {
            const [kind, id] = e.target.value.split(":");
            setParams({ owner: id, kind });
          }}
        >
          <optgroup label="Locations">
            {locations.map((location) => (
              <option key={location.id} value={`location:${location.id}`}>
                {location.name}
              </option>
            ))}
          </optgroup>
          <optgroup label="Resources">
            {resources.map((resource) => (
              <option key={resource.id} value={`resource:${resource.id}`}>
                {resource.name}
              </option>
            ))}
          </optgroup>
        </select>
        {zone && (
          <p className="text-xs text-gray-400 mt-2">
            Times below are local to <strong>{zone}</strong>, and stay correct
            through daylight-saving changes.
          </p>
        )}
        {ownerKind === "resource" && (
          <p className="text-xs text-gray-400 mt-1">
            A resource with no hours of its own simply follows its branch's.
            Add hours here only to narrow them.
          </p>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {!ownerId && locations.length === 0 && (
        <div className="empty-state">
          <Clock className="w-10 h-10 text-gray-300" strokeWidth={1.5} />
          <p className="empty-state-title">Add a location first</p>
          <p className="empty-state-desc">
            Opening hours belong to a branch, so there is nothing to set until one
            exists.
          </p>
        </div>
      )}

      {ownerId && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* --- Weekly hours --- */}
          <section className="card p-5">
            <h2 className="section-title mb-4">Weekly opening hours</h2>

            {rules === null ? (
              <div className="space-y-2" aria-busy="true">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="skeleton h-9 w-full" />
                ))}
              </div>
            ) : rules.length === 0 ? (
              <p className="text-sm text-gray-500 py-4">
                No opening hours set. Until at least one window exists, nothing
                here can be booked — a branch with no hours is treated as closed
                rather than as always open.
              </p>
            ) : (
              <ul className="space-y-1.5 mb-5">
                {WEEKDAY_LABELS.map((label, weekday) => {
                  const dayRules = byWeekday[weekday] ?? [];
                  if (dayRules.length === 0) return null;
                  return (
                    <li key={weekday} className="flex items-start gap-3 text-sm">
                      <span className="w-24 font-medium text-gray-700 pt-1">
                        {label}
                      </span>
                      <div className="flex-1 space-y-1">
                        {dayRules.map((rule) => (
                          <div
                            key={rule.id}
                            className="flex items-center gap-2 text-gray-600"
                          >
                            <span className="tabular-nums">
                              {toInputTime(rule.start_time)} –{" "}
                              {toInputTime(rule.end_time)}
                            </span>
                            <button
                              onClick={() => removeRule(rule.id)}
                              aria-label={`Remove ${label} ${toInputTime(rule.start_time)} to ${toInputTime(rule.end_time)}`}
                              className="btn-ghost p-1 h-auto text-gray-400 hover:text-red-500"
                            >
                              <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                            </button>
                          </div>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <form onSubmit={addRule} className="flex flex-wrap items-end gap-2 border-t chrome-rule pt-4">
              <div>
                <label className="label" htmlFor="rule-day">
                  Day
                </label>
                <select
                  id="rule-day"
                  className="input py-1.5"
                  value={ruleForm.weekday}
                  onChange={(e) =>
                    setRuleForm({ ...ruleForm, weekday: Number(e.target.value) })
                  }
                >
                  {WEEKDAY_LABELS.map((label, index) => (
                    <option key={label} value={index}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="rule-from">
                  From
                </label>
                <input
                  id="rule-from"
                  type="time"
                  className="input py-1.5"
                  value={ruleForm.start_time}
                  onChange={(e) =>
                    setRuleForm({ ...ruleForm, start_time: e.target.value })
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="rule-to">
                  To
                </label>
                <input
                  id="rule-to"
                  type="time"
                  className="input py-1.5"
                  value={ruleForm.end_time}
                  onChange={(e) =>
                    setRuleForm({ ...ruleForm, end_time: e.target.value })
                  }
                />
              </div>
              <button type="submit" disabled={busy} className="btn-secondary btn-sm">
                <Plus className="w-3.5 h-3.5" strokeWidth={2} />
                Add
              </button>
            </form>
          </section>

          {/* --- Closures --- */}
          <section className="card p-5">
            <h2 className="section-title mb-4">Holidays, leave and maintenance</h2>

            {blocks === null ? (
              <div className="space-y-2" aria-busy="true">
                {[0, 1].map((i) => (
                  <div key={i} className="skeleton h-9 w-full" />
                ))}
              </div>
            ) : blocks.length === 0 ? (
              <p className="text-sm text-gray-500 py-4">
                Nothing blocked out. Adding a closure stops new bookings — it
                never cancels appointments that already exist.
              </p>
            ) : (
              <ul className="space-y-2 mb-5">
                {blocks.map((block) => (
                  <li
                    key={block.id}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <div>
                      <div className="text-gray-700">
                        {new Date(block.starts_at).toLocaleString()} →{" "}
                        {new Date(block.ends_at).toLocaleString()}
                      </div>
                      {block.reason && (
                        <div className="text-xs text-gray-400">{block.reason}</div>
                      )}
                    </div>
                    <button
                      onClick={() => removeBlock(block.id)}
                      aria-label="Remove closure"
                      className="btn-ghost p-1 h-auto text-gray-400 hover:text-red-500"
                    >
                      <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <form onSubmit={addBlock} className="space-y-3 border-t chrome-rule pt-4">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="label" htmlFor="block-from">
                    From
                  </label>
                  <input
                    id="block-from"
                    type="datetime-local"
                    required
                    className="input py-1.5"
                    value={blockForm.starts_at}
                    onChange={(e) =>
                      setBlockForm({ ...blockForm, starts_at: e.target.value })
                    }
                  />
                </div>
                <div>
                  <label className="label" htmlFor="block-to">
                    To
                  </label>
                  <input
                    id="block-to"
                    type="datetime-local"
                    required
                    className="input py-1.5"
                    value={blockForm.ends_at}
                    onChange={(e) =>
                      setBlockForm({ ...blockForm, ends_at: e.target.value })
                    }
                  />
                </div>
              </div>
              <div>
                <label className="label" htmlFor="block-reason">
                  Reason
                </label>
                <input
                  id="block-reason"
                  className="input py-1.5"
                  value={blockForm.reason}
                  onChange={(e) =>
                    setBlockForm({ ...blockForm, reason: e.target.value })
                  }
                  placeholder="Annual leave"
                />
              </div>
              <button
                type="submit"
                disabled={busy || !blockForm.starts_at || !blockForm.ends_at}
                className="btn-secondary btn-sm"
              >
                <CalendarOff className="w-3.5 h-3.5" strokeWidth={2} />
                Block this time
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
