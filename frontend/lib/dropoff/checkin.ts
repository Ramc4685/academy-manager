/**
 * Parent drop-off check-in: what each persona sees, derived only from the
 * server's check-in state (so it survives a refresh) plus the last request's
 * error. A report is never attendance; only a staff confirmation is.
 */

import { formatAcademyClock } from "@/lib/format/academy-time";

type CheckinState = "none" | "pending" | "confirmed" | "expired";

interface CheckinLike {
  state: CheckinState;
  can_report_arrival?: boolean;
}

export type ParentArrivalView = "hidden" | "report" | "pending" | "confirmed";

/** Which arrival control a parent's class row shows. Expired reports show nothing. */
export function parentArrivalView(entry: {
  status: string;
  checkin?: CheckinLike | null;
  can_report_arrival?: boolean;
}): ParentArrivalView {
  const checkin = entry.checkin;
  if (!checkin || entry.status === "cancelled") return "hidden";
  if (checkin.state === "confirmed") return "confirmed";
  if (checkin.state === "pending") return "pending";
  return (entry.can_report_arrival ?? checkin.can_report_arrival) ? "report" : "hidden";
}

interface ErrorLike {
  status?: number;
  code?: string;
  details?: Record<string, unknown>;
}

/**
 * Copy for a failed "I've arrived". Every message says staff did NOT get it.
 * `retryable` is false when trying again cannot help (window closed, class
 * cancelled, feature off): the caller refetches so the button disappears.
 */
export function arrivalFailure(err: unknown): { message: string; retryable: boolean } {
  const e = (typeof err === "object" && err !== null ? err : {}) as ErrorLike;
  const notSent = "Staff have NOT received your arrival.";
  if (e.code === "Coaching.DropoffWindowClosed") {
    const reason = e.details?.reason;
    const why =
      reason === "not_open_yet"
        ? "Check-in isn't open yet for this class."
        : reason === "cancelled"
          ? "This class is cancelled."
          : "Check-in has closed for this class.";
    return { message: `${why} ${notSent} Please tell a coach in person.`, retryable: false };
  }
  if (e.code === "Coaching.DropoffCheckinDisabled" || e.code === "Coaching.StudentNotEnrolled") {
    return { message: `${notSent} Please tell a coach in person.`, retryable: false };
  }
  if (typeof e.status !== "number") {
    // fetch rejected before any response: offline, dropped, or timed out.
    return { message: `No connection. ${notSent} Check your signal and try again.`, retryable: true };
  }
  return { message: `Something went wrong. ${notSent} Try again.`, retryable: true };
}

interface StaffCheckinLike {
  reported_at?: string | null;
  reported_by_name?: string | null;
  confirmed_at?: string | null;
  confirmed_by_name?: string | null;
}

/** "Reported by Pat Kim at 5:42 PM CST · Confirmed by Sam Lee at 5:50 PM CST", in academy time. */
export function checkinActorLine(c: StaffCheckinLike, academyTimezone: string | null): string {
  const parts: string[] = [];
  if (c.reported_at) {
    parts.push(
      `Reported by ${c.reported_by_name || "parent"} at ${formatAcademyClock(c.reported_at, academyTimezone)}`,
    );
  }
  if (c.confirmed_at) {
    parts.push(
      `Confirmed by ${c.confirmed_by_name || "staff"} at ${formatAcademyClock(c.confirmed_at, academyTimezone)}`,
    );
  }
  return parts.join(" · ");
}
