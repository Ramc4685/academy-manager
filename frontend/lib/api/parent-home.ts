/**
 * Parent home aggregate (`GET /parent/home`).
 *
 * Kept in its own client module (rather than folded into the 700-line
 * `lib/api/parent.ts`) because it is the one parent read that fans out
 * server-side: Home renders N children without paying 2N round trips on a
 * phone. Types mirror the slice-4 contract field for field.
 */

import { apiFetch } from "./client";

export interface ParentHomeNextSession {
  occurrence_id: string;
  session_id: string;
  session_title: string;
  /** Venue; null when unset. */
  location: string | null;
  /** ISO-8601 UTC instant — render in the academy timezone, never the device's. */
  start_at: string;
  end_at: string;
  /** S45: who coaches this date (substitute, else the class coach); null when unknown. */
  coach_name: string | null;
  /** #1038: "makeup" / "trial" for a one-time approved class; optional for older payloads. */
  source?: "regular" | "makeup" | "trial";
  /** S17: the family reported this class as an absence. */
  absence_reported?: boolean;
  /** S45: family info stored on the class (address falls back to the academy's). */
  venue_address?: string | null;
  parking_notes?: string | null;
  what_to_bring?: string | null;
  arrival_minutes_before?: number | null;
}

export interface ParentHomeAttendance {
  /** Records marked `present` this academy-local month. */
  present: number;
  /** Every marked record this academy-local month, whatever the status. */
  total: number;
}

export interface ParentHomeMilestone {
  /** S18: "skill" is a passed skill (a milestone); "working_on" is still in progress. */
  kind: "note" | "skill" | "working_on";
  label: string;
  /** ISO-8601 UTC instant. */
  at: string;
}

export interface ParentHomeChild {
  student_id: string;
  full_name: string;
  next_session: ParentHomeNextSession | null;
  attendance_this_month: ParentHomeAttendance;
  latest_milestone: ParentHomeMilestone | null;
  /** S45: never marked present or late yet; Home shows "Before your first class". */
  first_class_pending?: boolean;
}

export interface ParentHomeBalance {
  /** 0 when nothing is due. */
  amount_due_cents: number;
  /** Stored lowercase (e.g. "usd"); the UI uppercases for display. */
  currency: string;
  /** Earliest due date among unpaid invoices; null when none. */
  due_date: string | null;
  open_invoice_count: number;
  payment_failed: boolean;
}

export interface ParentHomeResponse {
  children: ParentHomeChild[];
  balance: ParentHomeBalance;
  /** Month name in the academy timezone, e.g. "September". */
  month_label: string;
  /** Academy timezone, e.g. "America/Chicago". */
  timezone: string;
}

export function getParentHome(): Promise<ParentHomeResponse> {
  return apiFetch("/parent/home", { method: "GET" });
}
