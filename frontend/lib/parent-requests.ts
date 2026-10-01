import type { ChipVariant } from "@/components/ds/chip";
import type { AssignedClassView } from "@/lib/api/parent";
import { formatAcademyTimeRange } from "@/lib/format/academy-time";

/**
 * Maps backend request-status strings to Chip variants for the parent
 * Requests page (absences, makeups, trials). Kept as a pure function so it
 * can be unit-tested without mounting the page — the page itself only ever
 * displays whatever status/fee/timing the backend returns (no client-side
 * policy math).
 */
export function requestStatusChipVariant(status: string): ChipVariant {
  switch (status) {
    case "pending":
      return "pending";
    case "approved":
      return "approved";
    case "denied":
      return "denied";
    case "expired":
      return "expired";
    case "converted":
      return "converted";
    default:
      return "pending";
  }
}

export interface AssignedClassCopy {
  title: string;
  /** Academy-local date + time range with an explicit timezone label. */
  when: string;
  where: string;
  /** The class was called off after approval (#671) — never "attend here". */
  cancelled: boolean;
}

/**
 * Display copy for the class an approved make-up / trial puts the child in
 * (#1038). Formats in the academy timezone the backend resolved, falling
 * back to the page's academy timezone, never a hard-coded offset.
 */
export function assignedClassCopy(
  assigned: AssignedClassView | null | undefined,
  fallbackTimezone: string | null | undefined,
): AssignedClassCopy | null {
  if (!assigned) return null;
  return {
    title: assigned.session_title,
    when: formatAcademyTimeRange(
      assigned.start_at,
      assigned.end_at,
      assigned.timezone ?? fallbackTimezone,
    ),
    where: assigned.location ?? "Venue to be confirmed",
    cancelled: assigned.status === "cancelled",
  };
}
