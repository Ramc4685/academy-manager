import type { ChipVariant } from "@/components/ds/chip";
import type {
  AbsenceMakeupView,
  AssignedClassView,
  MakeupCandidatesResponse,
  MakeupCandidateView,
} from "@/lib/api/parent";
import { formatAcademyDate, formatAcademyTimeRange } from "@/lib/format/academy-time";

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

/** #1037: siblings in one class share an occurrence, so the key needs both ids. */
export function makeupCandidateKey(c: Pick<MakeupCandidateView, "student_id" | "occurrence_id">): string {
  return `${c.student_id}:${c.occurrence_id}`;
}

/** "Child — Class — date and time" in the academy timezone (#1037). */
export function makeupCandidateLabel(c: MakeupCandidateView, academyTimezone: string | null): string {
  return `${c.student_name} — ${c.class_title} — ${formatAcademyTimeRange(c.start_at, c.end_at, academyTimezone)}`;
}

/**
 * #1041: why the makeup picker is empty, so "nothing to pick" never reads the
 * same as "makeups are off" or "this academy needs an on-time notice".
 */
export function makeupEmptyMessage(
  data: Pick<MakeupCandidatesResponse, "makeups_enabled" | "requires_notice">,
): string {
  if (!data.makeups_enabled) return "Makeup requests are turned off for this academy.";
  if (data.requires_notice) {
    return "No missed classes available for a makeup request. This academy needs an on-time absence notice before a missed class can be made up.";
  }
  return "No missed classes available for a makeup request.";
}

/** Makeups tab, pre-selecting one child's missed class (the eligible offer). */
export function makeupBookingHref(studentId: string, occurrenceId: string): string {
  return `/parent/requests?tab=makeups&makeup=${encodeURIComponent(
    makeupCandidateKey({ student_id: studentId, occurrence_id: occurrenceId }),
  )}`;
}

export interface AbsenceMakeupDisplay {
  label: string;
  chip: ChipVariant;
  /** One plain-words line under the label, or null. */
  detail: string | null;
  /** Set only when a makeup can be requested now. */
  bookHref: string | null;
}

/**
 * How a reported absence's makeup state reads (Requests → Absences, Children).
 * Display only: the state, dates and reason all come from the server.
 */
export function absenceMakeupDisplay(
  makeup: AbsenceMakeupView | null | undefined,
  ids: { studentId: string; occurrenceId: string },
  academyTimezone: string | null,
): AbsenceMakeupDisplay {
  const until = (iso: string | null | undefined) =>
    iso ? formatAcademyDate(iso, academyTimezone) : "";
  switch (makeup?.state) {
    case "eligible":
      return {
        label: "Makeup eligible",
        chip: "open",
        detail: makeup.expires_at ? `Request a makeup by ${until(makeup.expires_at)}` : null,
        bookHref: makeupBookingHref(ids.studentId, ids.occurrenceId),
      };
    case "requested":
      return {
        label: "Makeup requested",
        chip: "pending",
        detail: "Waiting for the academy to confirm a class",
        bookHref: null,
      };
    case "booked": {
      const booked = assignedClassCopy(makeup.booked_class, academyTimezone);
      return {
        label: "Makeup booked",
        chip: "makeup",
        detail: booked ? `${booked.title} — ${booked.when}` : null,
        bookHref: null,
      };
    }
    case "expired":
      return {
        label: "Makeup expired",
        chip: "expired",
        detail: "The window to make up this class has passed",
        bookHref: null,
      };
    default:
      return {
        label: "Reported",
        chip: "approved",
        detail: makeup?.reason ?? null,
        bookHref: null,
      };
  }
}
