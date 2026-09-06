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
  /**
   * Always null today: the child-schedule use case hardcodes it. The field is
   * kept for shape parity with the schedule view model, and the card renders
   * the coach line only when it is non-null.
   */
  coach_name: string | null;
}

export interface ParentHomeAttendance {
  /** Records marked `present` this academy-local month. */
  present: number;
  /** Every marked record this academy-local month, whatever the status. */
  total: number;
}

export interface ParentHomeMilestone {
  kind: "note" | "skill";
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
