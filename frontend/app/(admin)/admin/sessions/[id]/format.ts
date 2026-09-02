import { type AdminSessionView, type EditSessionRequest } from "@/lib/api/admin";

const DEFAULT_TIMEZONE = "UTC";

// Shared sticky-action-column classes used by ReplacementCoachTable, RosterTable,
// and WaitlistTable. Not a "pure format helper" in the strictest sense, but kept
// here (rather than a fourth tiny file) since all three consumers already import
// from ./format — see MT5 split judgment calls.
export const actionHeaderClass =
  "sticky right-0 z-10 bg-white shadow-[-12px_0_16px_-18px_rgba(15,23,42,0.5)]";
export const actionCellClass =
  "sticky right-0 z-10 px-4 py-3 shadow-[-12px_0_16px_-18px_rgba(15,23,42,0.5)]";

// Shared text-input class used across SessionEditing.tsx and dialogs.tsx dialogs.
export const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

export function formatClock(time: string | null | undefined): string {
  if (!time) return "";
  const [hourText = "0", minuteText = "00"] = time.split(":");
  const hour = Number(hourText);
  if (!Number.isFinite(hour)) return time;
  const period = hour >= 12 ? "PM" : "AM";
  const hour12 = hour % 12 || 12;
  return `${hour12}:${minuteText.padStart(2, "0")} ${period}`;
}

export function sessionTimeRange(session: AdminSessionView): string {
  if (session.start_time && session.end_time) {
    return `${formatClock(session.start_time)} – ${formatClock(session.end_time)}`;
  }
  return `${new Date(session.start_at).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })} – ${new Date(session.end_at).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

export function formatCurrencyCents(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

export function centsToDollarsInput(cents: number | null | undefined): string {
  if (cents == null) return "";
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

export function dollarsInputToCents(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * 100);
}

export function hasRecurringSchedule(session: AdminSessionView): boolean {
  // Defensive `?.`: a payload without `days_of_week` used to throw here and take
  // the whole session-detail page down to the error boundary (same class as #503).
  return Boolean(session.days_of_week?.length && session.start_time && session.end_time);
}

export function sessionDateLabel(session: AdminSessionView): string {
  return new Date(session.start_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// --- Communication pack (#613) ---------------------------------------------

export interface CommunicationPack {
  whatsapp_group_link: string | null;
  venue_address: string | null;
  parking_notes: string | null;
  what_to_bring: string | null;
  arrival_minutes_before: number | null;
  coach_contact_policy: string | null;
  absence_policy: string | null;
}

export function communicationPackFields(session: AdminSessionView): CommunicationPack {
  return {
    whatsapp_group_link: session.whatsapp_group_link ?? null,
    venue_address: session.venue_address ?? null,
    parking_notes: session.parking_notes ?? null,
    what_to_bring: session.what_to_bring ?? null,
    arrival_minutes_before: session.arrival_minutes_before ?? null,
    coach_contact_policy: session.coach_contact_policy ?? null,
    absence_policy: session.absence_policy ?? null,
  };
}

export function hasCommunicationPack(session: AdminSessionView): boolean {
  return Object.values(communicationPackFields(session)).some(
    (value) => value !== null && String(value).trim() !== "",
  );
}

export function formatArrivalMinutes(minutes: number | null | undefined): string {
  if (minutes == null) return "";
  return `${minutes} minute${minutes === 1 ? "" : "s"} before start`;
}

/** Empty string is how the form clears a field; send null so the API clears it. */
export function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Client-side hint only. The server is the authority (it enforces a scheme
 * allowlist twice), so this never blocks a submit — it just stops the obvious
 * paste mistake before a round trip.
 */
export function looksLikeWebUrl(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed === "") return true;
  return /^https?:\/\/\S+$/i.test(trimmed);
}

export function buildEditSessionForm(session: AdminSessionView): EditSessionRequest {
  const common = {
    coach_id: session.coach_id,
    title: session.title,
    location: session.location,
    capacity: session.capacity,
    amount_cents: session.amount_cents,
    // Communication pack (#613). A field missing from this seed shows the
    // admin an empty box for a value that IS set, and because the PATCH body
    // is built with exclude_unset the stored value quietly survives — so the
    // form looks broken while the data is fine.
    ...communicationPackFields(session),
    reason: "",
  };
  if (hasRecurringSchedule(session)) {
    return {
      ...common,
      days_of_week: [...session.days_of_week],
      start_time: session.start_time,
      end_time: session.end_time,
      timezone: session.timezone ?? DEFAULT_TIMEZONE,
    };
  }
  return {
    ...common,
    start_at: session.start_at,
    end_at: session.end_at,
    days_of_week: [],
    start_time: null,
    end_time: null,
    timezone: session.timezone ?? DEFAULT_TIMEZONE,
  };
}

export function formatLocalDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function todayDateInput(): string {
  return formatLocalDateInput(new Date());
}

export function dateInputValueFromOffset(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return formatLocalDateInput(value);
}

export function toDateInputValue(value: string): string {
  return formatLocalDateInput(new Date(value));
}

export function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export function formatShortDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatDateOnly(value: string): string {
  if (!value) return "date pending";
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatEnrollmentDate(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Not recorded" : parsed.toLocaleDateString();
}

export function formatLifecycleType(value: string): string {
  const labels: Record<string, string> = {
    created: "Added",
    moved: "Moved",
    paused: "Paused",
    resumed: "Resumed",
    withdrawn: "Withdrawn",
    removed: "Removed",
    cancelled: "Cancelled",
    waitlisted: "Waitlisted",
    promoted: "Promoted",
  };
  return labels[value] ?? "Updated";
}
