/**
 * "Am I done marking?" — the one question the coach app could not answer
 * (issue #777).
 *
 * `/coach/today` has always returned `attendance_status` per roster row, but
 * every coach screen showed a student COUNT, so a class with two of nine
 * students marked looked exactly like a finished one. These helpers turn the
 * roster the API already sends into "n/N marked", and pick out the classes of
 * the last 48 hours that were never finished.
 *
 * Pure functions in the node vitest environment — no React, no fetch.
 */

import { parseAcademyInstant } from "@/lib/format/academy-time";

export interface MarkableRosterEntry {
  student_id: string;
  attendance_status?: string | null;
  enrollment_status?: string | null;
}

/** A status that counts as a mark. "voided" (an admin annulled it) does not. */
export function isRecordedMark(status: string | null | undefined): boolean {
  return status === "present" || status === "absent" || status === "late";
}

/** Seats the server refuses to mark (#1040): they cannot make a register incomplete. */
const UNMARKABLE_ENROLLMENT: ReadonlySet<string> = new Set([
  "held",
  "reclaim_pending",
]);

/** How long a coach may change their own mark; after that only an admin can. */
export const COACH_CORRECTION_WINDOW_MS = 48 * 60 * 60 * 1000;

/** How early before the start time a class can be marked (server: MARK_LEAD_TIME). */
export const MARK_LEAD_TIME_MS = 60 * 60 * 1000;

export function correctionWindowClosed(
  markedAt: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!markedAt) return false;
  const at = new Date(markedAt).getTime();
  return !Number.isNaN(at) && now.getTime() - at > COACH_CORRECTION_WINDOW_MS;
}

/** True when the class is still too far in the future to take attendance. */
export function markingNotOpenYet(
  startAt: string,
  now: Date = new Date(),
): boolean {
  // Same parser as the "opens at" label: a naive timestamp is UTC (server truth).
  const start = parseAcademyInstant(startAt).getTime();
  return !Number.isNaN(start) && start - now.getTime() > MARK_LEAD_TIME_MS;
}

export interface MarkableSession {
  occurrence_id: string;
  start_at: string;
  roster: MarkableRosterEntry[];
  status?: string | null;
}

export interface MarkProgress {
  marked: number;
  total: number;
  /** True when nothing is left to mark — including an empty roster. */
  complete: boolean;
  /** "2/9 marked" — the header/badge text. */
  label: string;
}

/**
 * How much of a roster is marked.
 *
 * `alsoMarked` carries ids marked on this device but not yet reflected in the
 * fetched roster (an optimistic tap, a queued offline mark), so the header
 * doesn't count down a beat behind the coach's own thumb.
 */
export function markProgress(
  roster: readonly MarkableRosterEntry[],
  alsoMarked: ReadonlySet<string> = new Set(),
): MarkProgress {
  const isMarked = (entry: MarkableRosterEntry): boolean =>
    isRecordedMark(entry.attendance_status) || alsoMarked.has(entry.student_id);
  // A held seat with no mark is shown for context but cannot be marked, so it
  // is not owed a mark; once marked it counts like any other row.
  const owed = roster.filter(
    (entry) =>
      isMarked(entry) ||
      !UNMARKABLE_ENROLLMENT.has(entry.enrollment_status ?? ""),
  );
  const total = owed.length;
  const marked = owed.filter(isMarked).length;
  return {
    marked,
    total,
    // An empty roster has nothing to mark: never badge it "Needs marks".
    complete: marked >= total,
    label: `${marked}/${total} marked`,
  };
}

/** True when this dated class was called off (#777 — it still shows, struck through). */
export function isCancelled(session: { status?: string | null }): boolean {
  return session.status === "cancelled";
}

/**
 * Link to one dated class.
 *
 * The session screen is occurrence-scoped and needs the class's LOCAL date to
 * resolve the roster; a link without it (the coach calendar's old
 * `/coach/sessions/<session_id>`) lands on the wrong day or on "Session not
 * found."
 */
export function coachSessionHref(
  occurrenceId: string,
  dateISO?: string | null,
): string {
  const path = `/coach/sessions/${encodeURIComponent(occurrenceId)}`;
  return dateISO ? `${path}?date=${dateISO}` : path;
}

/** How far back "recent, not fully marked" looks. */
export const RECENT_UNMARKED_WINDOW_MS = 48 * 60 * 60 * 1000;

/**
 * Classes that already happened in the last 48 hours and still have unmarked
 * students — the register a coach forgot to close, which nothing used to
 * surface once the day rolled over.
 *
 * Cancelled classes and empty rosters are never "unfinished". The input may
 * span overlapping day queries (an evening class lands on two of them), so
 * occurrences are de-duplicated.
 */
export function recentUnmarkedSessions<T extends MarkableSession>(
  sessions: readonly T[],
  now: Date = new Date(),
): T[] {
  const nowMs = now.getTime();
  const floor = nowMs - RECENT_UNMARKED_WINDOW_MS;
  const seen = new Set<string>();
  return sessions
    .filter((session) => {
      if (seen.has(session.occurrence_id)) return false;
      seen.add(session.occurrence_id);
      if (isCancelled(session)) return false;
      if (session.roster.length === 0) return false;
      const started = new Date(session.start_at).getTime();
      if (Number.isNaN(started) || started > nowMs || started < floor)
        return false;
      return !markProgress(session.roster).complete;
    })
    .sort(
      (a, b) => new Date(b.start_at).getTime() - new Date(a.start_at).getTime(),
    );
}

/**
 * Hand a mark to the offline queue: drop this row's unconfirmed local entry
 * (an error, or an optimistic tap still `pending` when the request died) so
 * the queued state is what the row shows. A confirmed save is kept.
 */
export function withoutUnconfirmedMark<
  T extends { pending: boolean; error?: string },
>(marks: Record<string, T>, student_id: string): Record<string, T> {
  const entry = marks[student_id];
  if (!entry || !(entry.error || entry.pending)) return marks;
  const next = { ...marks };
  delete next[student_id];
  return next;
}

/**
 * The coach's next class that has not started yet, from the upcoming schedule
 * (`GET /coach/sessions`). Used by Today's empty state.
 */
export function nextUpcomingClass<T extends { start_at: string }>(
  schedule: readonly T[],
  now: Date = new Date(),
): T | null {
  const nowMs = now.getTime();
  let best: T | null = null;
  let bestMs = Infinity;
  for (const entry of schedule) {
    const ms = new Date(entry.start_at).getTime();
    if (Number.isNaN(ms) || ms <= nowMs || ms >= bestMs) continue;
    best = entry;
    bestMs = ms;
  }
  return best;
}

/**
 * The most recent class of the last 48 hours whose recap still names no
 * taught skill (`recap_saved` from `/coach/today`). Cancelled classes and
 * empty rosters never need a recap. Same window as "recent, not fully marked".
 */
export function latestUnfinishedRecap<
  T extends MarkableSession & { recap_saved?: boolean | null },
>(sessions: readonly T[], now: Date = new Date()): T | null {
  const nowMs = now.getTime();
  const floor = nowMs - RECENT_UNMARKED_WINDOW_MS;
  let best: T | null = null;
  let bestMs = -Infinity;
  for (const session of sessions) {
    if (
      session.recap_saved ||
      isCancelled(session) ||
      session.roster.length === 0
    )
      continue;
    // Everyone marked absent: there is no class to recap.
    if (session.roster.every((row) => row.attendance_status === "absent"))
      continue;
    const started = new Date(session.start_at).getTime();
    if (
      Number.isNaN(started) ||
      started > nowMs ||
      started < floor ||
      started <= bestMs
    )
      continue;
    best = session;
    bestMs = started;
  }
  return best;
}
