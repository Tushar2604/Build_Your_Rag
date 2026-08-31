// Appointments, availability, and the configuration behind them.
//
// One module for the whole scheduling surface: the pages are cross-referencing
// (a service edit needs the resource list, the calendar needs both) and
// splitting it would mean five files importing each other.
//
// Every time crossing this boundary is an ISO-8601 UTC instant. The branch's
// IANA timezone travels alongside it so the UI can render local time without
// guessing — never do date arithmetic on the formatted string.
import { api } from "./client";

export type AppointmentStatus =
  | "draft"
  | "requested"
  | "pending"
  | "awaiting_confirmation"
  | "confirmed"
  | "arrived"
  | "checked_in"
  | "in_progress"
  | "completed"
  | "cancelled"
  | "no_show"
  | "rescheduled"
  | "waitlisted";

export type BookingSource =
  | "staff"
  | "ai_voice"
  | "whatsapp"
  | "web_widget"
  | "booking_page"
  | "sms"
  | "email"
  | "mobile_app"
  | "portal"
  | "api"
  | "campaign";

export type ResourceKind = "staff" | "room" | "equipment" | "vehicle" | "other";
export type OwnerKind = "location" | "resource";

export interface Location {
  id: string;
  name: string;
  timezone: string;
  address: string;
  phone: string;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface ServiceResourceLink {
  resource_id: string;
  role: string;
  required: boolean;
}

export interface Service {
  id: string;
  name: string;
  category: string;
  description: string;
  duration_minutes: number;
  buffer_before_minutes: number;
  buffer_after_minutes: number;
  price_cents: number;
  deposit_cents: number;
  currency: string;
  min_notice_minutes: number;
  max_horizon_days: number;
  cancellation_window_hours: number;
  online_bookable: boolean;
  is_active: boolean;
  resources: ServiceResourceLink[];
  created_at: string;
}

export interface Resource {
  id: string;
  name: string;
  kind: ResourceKind;
  location_id: string | null;
  user_id: string | null;
  email: string;
  phone: string;
  capacity: number;
  timezone: string;
  color: string;
  is_active: boolean;
  created_at: string;
}

export interface AvailabilityRule {
  id: string;
  owner_kind: OwnerKind;
  owner_id: string;
  /** Monday = 0, matching the backend and `Date.getDay()` shifted by one. */
  weekday: number;
  /** Wall-clock local time ("09:00:00"), NOT an instant. */
  start_time: string;
  end_time: string;
  effective_from: string | null;
  effective_until: string | null;
  is_active: boolean;
}

export interface BlockedPeriod {
  id: string;
  owner_kind: OwnerKind;
  owner_id: string;
  starts_at: string;
  ends_at: string;
  reason: string;
}

export interface Slot {
  starts_at: string;
  ends_at: string;
  /** Exactly the resources booking this slot would reserve. Not advisory. */
  resource_ids: string[];
}

export interface AvailabilityResult {
  location_id: string;
  service_id: string;
  timezone: string;
  duration_minutes: number;
  slots: Slot[];
}

export interface SlotHold {
  token: string;
  starts_at: string;
  ends_at: string;
  expires_at: string;
  resource_ids: string[];
}

export interface Appointment {
  id: string;
  location_id: string;
  service_id: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: AppointmentStatus;
  source: BookingSource;
  customer_name: string;
  customer_phone: string;
  customer_email: string;
  customer_timezone: string;
  resource_ids: string[];
  customer_notes: string;
  internal_notes: string;
  cancellation_reason: string;
  rescheduled_from_id: string | null;
  location_name: string;
  service_name: string;
  resource_names: string[];
  created_at: string;
  updated_at: string;
}

export interface AppointmentPage {
  appointments: Appointment[];
  total: number;
  page: number;
  page_size: number;
}

export interface AppointmentHistoryEntry {
  from_status: string;
  to_status: string;
  actor_kind: string;
  actor_label: string;
  channel: string;
  reason: string;
  occurred_at: string;
}

export interface AppointmentSummary {
  window_start: string;
  window_end: string;
  total: number;
  by_status: Record<string, number>;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

// --- Locations ---
export const locationsApi = {
  list: (activeOnly = false) =>
    api.get<Location[]>(`/locations${qs({ active_only: activeOnly })}`),
  create: (body: Partial<Location>) => api.post<Location>("/locations", body),
  update: (id: string, body: Partial<Location>) =>
    api.put<Location>(`/locations/${id}`, body),
  deactivate: (id: string) => api.delete<void>(`/locations/${id}`),
};

// --- Services ---
export const servicesApi = {
  list: (activeOnly = false) =>
    api.get<Service[]>(`/services${qs({ active_only: activeOnly })}`),
  create: (body: Partial<Service>) => api.post<Service>("/services", body),
  update: (id: string, body: Partial<Service>) =>
    api.put<Service>(`/services/${id}`, body),
  /** Replaces the whole eligibility set — the editor always sends all of it. */
  setResources: (id: string, resources: ServiceResourceLink[]) =>
    api.put<Service>(`/services/${id}/resources`, { resources }),
  deactivate: (id: string) => api.delete<void>(`/services/${id}`),
};

// --- Resources ---
export const resourcesApi = {
  list: (opts: { locationId?: string; kind?: string; activeOnly?: boolean } = {}) =>
    api.get<Resource[]>(
      `/resources${qs({
        location_id: opts.locationId,
        kind: opts.kind,
        active_only: opts.activeOnly,
      })}`,
    ),
  create: (body: Partial<Resource>) => api.post<Resource>("/resources", body),
  update: (id: string, body: Partial<Resource>) =>
    api.put<Resource>(`/resources/${id}`, body),
  deactivate: (id: string) => api.delete<void>(`/resources/${id}`),
};

// --- Availability rules and blocks ---
export const availabilityApi = {
  /** The authoritative slot list. Never compute availability in the browser. */
  find: (params: {
    location_id: string;
    service_id: string;
    range_start: string;
    range_end: string;
    resource_id?: string;
    granularity_minutes?: number;
    limit?: number;
  }) => api.get<AvailabilityResult>(`/availability${qs(params)}`),

  listRules: (ownerId: string) =>
    api.get<AvailabilityRule[]>(`/availability-rules${qs({ owner_id: ownerId })}`),
  createRule: (body: {
    owner_kind: OwnerKind;
    owner_id: string;
    weekday: number;
    start_time: string;
    end_time: string;
  }) => api.post<AvailabilityRule>("/availability-rules", body),
  deleteRule: (id: string) => api.delete<void>(`/availability-rules/${id}`),

  listBlocks: (ownerId: string) =>
    api.get<BlockedPeriod[]>(`/blocked-periods${qs({ owner_id: ownerId })}`),
  createBlock: (body: {
    owner_kind: OwnerKind;
    owner_id: string;
    starts_at: string;
    ends_at: string;
    reason?: string;
  }) => api.post<BlockedPeriod>("/blocked-periods", body),
  deleteBlock: (id: string) => api.delete<void>(`/blocked-periods/${id}`),
};

// --- Appointments ---
export interface BookingReadiness {
  ready: boolean;
  locations: number;
  services: number;
  resources: number;
  services_with_staff: number;
  resources_with_hours: number;
  /** In the order they have to be fixed. */
  blockers: string[];
}

export interface NewAppointments {
  count: number;
  /** Echoed back, so a real zero is distinguishable from a request sent with
   * the wrong watermark. */
  since: string;
  /** The newest booking's timestamp, or null when nothing is new. Clients
   * advance their watermark to this rather than to "now". */
  latest_at: string | null;
}

export const appointmentsApi = {
  list: (params: {
    /** "upcoming" (the default server-side) hides anything already finished;
     * "past" shows only those; "all" shows everything. Past appointments are
     * never deleted — they are the record of what the business did. */
    when?: "upcoming" | "past" | "all";
    range_start?: string;
    range_end?: string;
    location_id?: string;
    service_id?: string;
    resource_id?: string;
    status?: string;
    search?: string;
    page?: number;
    page_size?: number;
  }) => api.get<AppointmentPage>(`/appointments${qs(params)}`),

  summary: (rangeStart?: string, rangeEnd?: string) =>
    api.get<AppointmentSummary>(
      `/appointments/summary${qs({ range_start: rangeStart, range_end: rangeEnd })}`,
    ),

  /** Whether this workspace can actually book anything yet, and what is
   * missing if not. Four things have to exist before availability search
   * returns a single time; missing any one looks exactly like a broken
   * assistant from the outside. */
  readiness: () => api.get<BookingReadiness>("/appointments/readiness"),

  /** Bookings taken since `since` — the sidebar badge's number. Omitting
   * `since` asks for the last day, so a browser that has never looked does not
   * open with a badge in the hundreds. */
  newSince: (since?: string) =>
    api.get<NewAppointments>(`/appointments/new${qs({ since })}`),

  get: (id: string) => api.get<Appointment>(`/appointments/${id}`),

  create: (body: {
    location_id: string;
    service_id: string;
    starts_at: string;
    customer_name: string;
    customer_phone?: string;
    customer_email?: string;
    resource_id?: string | null;
    hold_token?: string;
    source?: BookingSource;
    status?: AppointmentStatus;
    customer_notes?: string;
    internal_notes?: string;
    idempotency_key?: string;
  }) => api.post<Appointment>("/appointments", body),

  update: (
    id: string,
    body: Partial<
      Pick<
        Appointment,
        | "customer_name"
        | "customer_phone"
        | "customer_email"
        | "customer_notes"
        | "internal_notes"
      >
    >,
  ) => api.patch<Appointment>(`/appointments/${id}`, body),

  history: (id: string) =>
    api.get<{ appointment_id: string; entries: AppointmentHistoryEntry[] }>(
      `/appointments/${id}/history`,
    ),

  reschedule: (id: string, startsAt: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/reschedule`, {
      starts_at: startsAt,
      reason,
    }),

  // Lifecycle. One call per verb rather than a status PATCH, so the server can
  // reject an illegal move and record who made a legal one.
  confirm: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/confirm`, { reason }),
  checkIn: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/check-in`, { reason }),
  start: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/start`, { reason }),
  complete: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/complete`, { reason }),
  cancel: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/cancel`, { reason }),
  noShow: (id: string, reason = "") =>
    api.post<Appointment>(`/appointments/${id}/no-show`, { reason }),
};

// --- Slot holds ---
export const slotHoldsApi = {
  create: (body: {
    location_id: string;
    service_id: string;
    starts_at: string;
    resource_id?: string | null;
  }) => api.post<SlotHold>("/slot-holds", body),
  release: (token: string) => api.delete<void>(`/slot-holds/${token}`),
};

// --- Display helpers -------------------------------------------------------

/** Human label for a status. Keyed on the wire value so an unknown status from
 *  a newer backend degrades to a readable string rather than blank. */
export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  requested: "Requested",
  pending: "Pending",
  awaiting_confirmation: "Awaiting confirmation",
  confirmed: "Confirmed",
  arrived: "Arrived",
  checked_in: "Checked in",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
  no_show: "No-show",
  rescheduled: "Rescheduled",
  waitlisted: "Waitlisted",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

/** Which badge a status wears. Grouped by what the user must DO about it:
 *  green = settled, amber = needs chasing, red = lost, grey = inert. */
export function statusBadgeClass(status: string): string {
  switch (status) {
    case "confirmed":
    case "checked_in":
    case "in_progress":
    case "completed":
    case "arrived":
      return "badge-live";
    case "pending":
    case "requested":
    case "awaiting_confirmation":
    case "waitlisted":
      return "badge-paused";
    case "cancelled":
    case "no_show":
      return "badge-error";
    default:
      return "badge-neutral";
  }
}

/**
 * Render a UTC instant in a named IANA zone.
 *
 * Always pass the appointment's own timezone rather than letting the browser
 * default: a receptionist in Dubai looking at a London branch must see London's
 * clock, and `toLocaleString` without a zone silently shows theirs.
 */
export function formatInZone(
  iso: string,
  timeZone: string,
  options: Intl.DateTimeFormatOptions = {},
): string {
  try {
    return new Date(iso).toLocaleString(undefined, { timeZone, ...options });
  } catch {
    // An unresolvable zone must not blank the whole cell — the instant is still
    // correct, only less friendly.
    return new Date(iso).toLocaleString(undefined, options);
  }
}

export function formatTimeInZone(iso: string, timeZone: string): string {
  return formatInZone(iso, timeZone, { hour: "2-digit", minute: "2-digit" });
}

export function formatDateInZone(iso: string, timeZone: string): string {
  return formatInZone(iso, timeZone, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

/** Minutes from local midnight, in the given zone — the calendar grid's y-axis. */
export function minutesFromMidnight(iso: string, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso));
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return hour * 60 + minute;
}

export const WEEKDAY_LABELS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

/** Backend weekdays are Monday = 0; JavaScript's `getDay()` is Sunday = 0. */
export function jsDayToBackendWeekday(jsDay: number): number {
  return (jsDay + 6) % 7;
}

export function money(cents: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "AED",
    }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`;
  }
}
