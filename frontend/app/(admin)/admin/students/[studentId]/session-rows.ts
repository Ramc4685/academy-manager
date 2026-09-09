/**
 * Pure view-model helpers for the student Sessions tab (issue #674).
 *
 * Kept free of React so the chip mapping and past-row wording are unit-tested
 * without rendering. The backend owns the facts; this only decides how a
 * fact is worded.
 */

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

export interface PastEnrollmentRow {
  enrollmentId: string;
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
    sessionTitle: row.session_title,
    location: row.location ?? null,
    statusLabel: status.label,
    statusVariant: status.variant,
    endedOn,
    endedBy: actor ? (ACTOR_LABELS[actor] ?? row.cancelled_by!.trim()) : "—",
    reason: row.reason?.trim() || "—",
  };
}
