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

export interface MarkableRosterEntry {
  student_id: string;
  attendance_status?: string | null;
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
  const total = roster.length;
  const marked = roster.filter(
    (entry) => Boolean(entry.attendance_status) || alsoMarked.has(entry.student_id),
  ).length;
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
export function coachSessionHref(occurrenceId: string, dateISO?: string | null): string {
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
      if (Number.isNaN(started) || started > nowMs || started < floor) return false;
      return !markProgress(session.roster).complete;
    })
    .sort((a, b) => new Date(b.start_at).getTime() - new Date(a.start_at).getTime());
}
