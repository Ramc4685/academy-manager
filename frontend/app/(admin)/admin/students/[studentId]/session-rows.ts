/**
 * Pure view-model helpers for the student Sessions tab (issue #674).
 *
 * Kept free of React so the chip mapping and past-row wording are unit-tested
 * without rendering. The backend owns the facts; this only decides how a
 * fact is worded.
 */

import {
  DEPARTURE_ACTION_DESCRIPTION,
  DEPARTURE_ACTION_LABEL,
  holdActionsFor,
  type DepartureAction,
} from "@/components/admin/enrollment/departure-actions.logic";
import type { ChipVariant } from "@/components/ds/chip";
import type { AdminStudentSessionSummary } from "@/lib/api/v2/students";

import { formatInvoiceDate } from "./format";

export interface AutopayChip {
  variant: ChipVariant;
  label: string;
}

/**
 * Billing's `autopay_enrollment_status` axis (not_offered | offered |
 * setup_started | active | paused | disabled) collapsed to the same three
 * admin-facing words the family billing page uses
 * (`families/[parentId]/StudentsPanel.tsx`): "Autopay" when it is on,
 * "Autopay off" when the family paused it, and "Manual" for everything else,
 * including the repository default `not_offered`, a merely `offered` setup
 * and a missing billing record. Only `setup_started` — a family part-way
 * through saving a card — reads as pending.
 */
export function autopayChip(status: string | null | undefined): AutopayChip {
  switch (status) {
    case "active":
      return { variant: "autopayOn", label: "Autopay" };
    case "paused":
      return { variant: "manual", label: "Autopay off" };
    case "setup_started":
      return { variant: "autopayPend", label: "Autopay pending" };
    case "not_offered":
    case "offered":
    case "disabled":
    case null:
    case undefined:
    case "":
    default:
      return { variant: "manual", label: "Manual" };
  }
}

export function familyBillingHref(parentId: string | null | undefined): string | null {
  return parentId ? `/admin/families/${encodeURIComponent(parentId)}` : null;
}

/**
 * Issue #827: where an admin goes to put a departed student back — the class
 * roster, whose Re-enroll action opens Add to roster pre-filled. The student
 * profile has no session picker of its own, and inventing one here would be a
 * second way to create an enrollment.
 */
export function sessionRosterHref(sessionId: string): string {
  return `/admin/sessions/${encodeURIComponent(sessionId)}`;
}

export interface PastEnrollmentRow {
  enrollmentId: string;
  /** #827: the class this row ended in, for the Re-enroll link. */
  sessionId: string;
  sessionTitle: string;
  location: string | null;
  statusLabel: string;
  statusVariant: ChipVariant;
  /**
   * `ended_at` (`cancelled_at` for cancels, `withdrawal_date` for
   * withdrawals). The writers mix calendar days stored at UTC midnight (admin
   * cancel and withdraw both stamp `_start_of_day_utc(effective_date)`, #215)
   * with real instants (parent self-cancel, session cancel), so the value is
   * rendered with the same midnight-means-a-day heuristic as invoice dates
   * regardless of status: a 9/1 admin cancel must not read as 8/31 in Chicago.
   */
  endedOn: string;
  endedBy: string;
  reason: string;
}

// A transfer moves the enrollment in place (no status change), so the
// enrollment read never yields a "transferred" past row.
//
// Issue #699: "cancelled"/"withdrawn" are the legacy spellings of
// "deleted"/"dropped" — both are mapped to the same label so a row from
// either era of backend code reads identically.
const STATUS_LABELS: Record<string, { label: string; variant: ChipVariant }> = {
  cancelled: { label: "Cancelled", variant: "expired" },
  deleted: { label: "Cancelled", variant: "expired" },
  withdrawn: { label: "Withdrawn", variant: "expired" },
  dropped: { label: "Withdrawn", variant: "expired" },
};

const ACTOR_LABELS: Record<string, string> = {
  admin: "Admin",
  parent: "Parent",
  system: "System",
};

export function pastEnrollmentRow(row: AdminStudentSessionSummary): PastEnrollmentRow {
  const status = STATUS_LABELS[row.status] ?? {
    label: row.status.replace(/_/g, " "),
    variant: "expired" as ChipVariant,
  };
  // Issue #699: "withdrawn"/"dropped" are the two spellings of the same
  // withdrawal outcome across the dual-read era.
  const withdrawn = row.status === "withdrawn" || row.status === "dropped";
  const endedAt =
    row.ended_at ??
    (withdrawn
      ? (row.withdrawal_date ?? row.cancelled_at)
      : (row.cancelled_at ?? row.withdrawal_date));
  const endedOn = formatInvoiceDate(endedAt);
  const actor = row.cancelled_by?.trim().toLowerCase() ?? "";
  return {
    enrollmentId: row.enrollment_id,
    sessionId: row.session_id,
    sessionTitle: row.session_title,
    location: row.location ?? null,
    statusLabel: status.label,
    statusVariant: status.variant,
    endedOn,
    endedBy: actor ? (ACTOR_LABELS[actor] ?? row.cancelled_by!.trim()) : "—",
    reason: row.reason?.trim() || "—",
  };
}

/**
 * Issue #865: what an admin can do to one enrolled session, in the order the
 * Sessions tab offers it.
 *
 * ONE derivation for both layouts. The desktop table renders these as its
 * inline Fee / Discount buttons plus `DepartureActions`; the phone row
 * renders the same list inside `PhoneListRow`'s 44px menu. If each layout
 * decided for itself which actions a status allows, the two would eventually
 * disagree about the same enrollment — a "second LAYOUT, never a second
 * derivation" (see `components/ds/phone-row.tsx`).
 *
 * Hold/Return comes from `holdActionsFor`, the helper the class roster
 * already shares, so both surfaces answer "can this row be held?" the same
 * way. Fee and Discount are this page's own: they edit the enrollment's
 * money, which the roster does not.
 */
export type EnrolledSessionActionKey = "hold" | "return" | "transfer" | "fee" | "discount";

export interface EnrolledSessionAction {
  key: EnrolledSessionActionKey;
  label: string;
  /** Seat / billing / family-email line for the departure actions (#859). */
  description?: string;
}

export function enrolledSessionActions(session: {
  status: string;
  discount?: { label?: string } | null;
}): EnrolledSessionAction[] {
  const departures: DepartureAction[] = [...holdActionsFor(session.status), "transfer"];
  return [
    ...departures.map((action) => ({
      key: action as EnrolledSessionActionKey,
      label: DEPARTURE_ACTION_LABEL[action],
      description: DEPARTURE_ACTION_DESCRIPTION[action],
    })),
    { key: "fee" as const, label: "Fee" },
    {
      key: "discount" as const,
      // Same words the table's button uses, so the phone menu is not a second
      // vocabulary for the same editor.
      label: session.discount ? "Edit discount" : "Discount",
    },
  ];
}
