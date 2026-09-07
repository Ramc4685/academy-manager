/**
 * Pure view-model helpers for the student Sessions tab (issue #674).
 *
 * Kept free of React so the chip mapping and past-row wording are unit-tested
 * without rendering. The backend owns the facts; this only decides how a
 * fact is worded.
 */

import type { ChipVariant } from "@/components/ds/chip";
import type { AdminStudentSessionSummary } from "@/lib/api/v2/students";

import { formatDate, formatDateUtc } from "./format";

export interface AutopayChip {
  variant: ChipVariant;
  label: string;
}

/**
 * Billing's `autopay_enrollment_status` axis collapsed to four admin-facing
 * states. Anything that is not on / paused / off (the setup_* states) reads as
 * pending, and a missing record (null) reads as "no autopay" rather than
 * pretending the family opted out.
 */
export function autopayChip(status: string | null | undefined): AutopayChip {
  switch (status) {
    case "active":
      return { variant: "autopayOn", label: "Autopay on" };
    case "paused":
      return { variant: "paused", label: "Autopay paused" };
    case "disabled":
      return { variant: "manual", label: "Autopay off" };
    case null:
    case undefined:
    case "":
      return { variant: "manual", label: "No autopay" };
    default:
      return { variant: "autopayPend", label: "Autopay pending" };
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
   * "cancelled_at" (an instant, local time) for cancels; "withdrawal_date"
   * (a calendar day stored at UTC midnight, so rendered in UTC — issue #215)
   * for withdrawals.
   */
  endedOn: string;
  endedBy: string;
  reason: string;
}

const STATUS_LABELS: Record<string, { label: string; variant: ChipVariant }> = {
  cancelled: { label: "Cancelled", variant: "expired" },
  withdrawn: { label: "Withdrawn", variant: "expired" },
  transferred_out: { label: "Transferred", variant: "transferred" },
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
  const withdrawn = row.status === "withdrawn";
  const endedAt =
    row.ended_at ??
    (withdrawn
      ? (row.withdrawal_date ?? row.cancelled_at)
      : (row.cancelled_at ?? row.withdrawal_date));
  const endedOn = !endedAt ? "—" : withdrawn ? formatDateUtc(endedAt) : formatDate(endedAt);
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
