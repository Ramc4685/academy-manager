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

export type ParentArrivalView = "hidden" | "report" | "pending" | "confirmed" | "expired";

/**
 * Which arrival control a parent's class row shows. An expired report (sent,
 * never confirmed) says so instead of silently disappearing.
 */
export function parentArrivalView(entry: {
  status: string;
  checkin?: CheckinLike | null;
  can_report_arrival?: boolean;
}): ParentArrivalView {
  const checkin = entry.checkin;
  if (!checkin || entry.status === "cancelled") return "hidden";
  if (checkin.state === "confirmed") return "confirmed";
  if (checkin.state === "pending") return "pending";
  if (checkin.state === "expired") return "expired";
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

/**
 * Copy for a refused staff confirm. An Absent/voided mark already stands as
 * the official record, so the confirm is refused (409) rather than shown as
 * "Checked in"; staff correct the mark instead. Null: use the generic copy.
 */
export function confirmFailureMessage(err: unknown): string | null {
  const e = (typeof err === "object" && err !== null ? err : {}) as ErrorLike;
  if (e.code !== "Coaching.ConflictAttendanceExists") return null;
  const status = e.details?.existing_status;
  if (status === "voided") {
    return "This child's attendance mark was voided. Correct it to Present to check them in.";
  }
  if (status === "absent") {
    return "This child is already marked Absent. Correct the mark to Present to check them in.";
  }
  return "This child already has an attendance mark. Refresh to see it.";
}

interface DropoffWindowLike {
  opensAt?: string | null;
  closesAt?: string | null;
  /** Nothing left to wait for (e.g. already checked in). */
  done?: boolean;
}

const POLL_MS = 30_000;
const LOOKAHEAD_MS = 12 * 60 * 60_000;

/**
 * react-query `refetchInterval` while a drop-off window matters: one refetch
 * the moment a window opens (so "I've arrived" appears without a reload),
 * then every 30 s until a minute after it closes. False when nothing is near,
 * so an idle screen never polls.
 */
export function dropoffRefetchInterval(
  windows: readonly DropoffWindowLike[],
  now: number = Date.now(),
): number | false {
  let next: number | false = false;
  for (const w of windows) {
    if (w.done || !w.opensAt || !w.closesAt) continue;
    const opens = Date.parse(w.opensAt);
    const closes = Date.parse(w.closesAt);
    let wait: number | null = null;
    if (now < opens) wait = opens - now <= LOOKAHEAD_MS ? Math.max(opens - now, 5_000) : null;
    else if (now <= closes + 60_000) wait = POLL_MS;
    if (wait !== null && (next === false || wait < next)) next = wait;
  }
  return next;
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
