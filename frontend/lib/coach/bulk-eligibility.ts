/**
 * Who belongs in a "Mark rest present" batch (issue #866).
 *
 * The bulk endpoint is the authority on eligibility: it rejects the WHOLE
 * batch with `Coaching.BulkStudentNotEnrolled` when any student is neither
 * actively enrolled nor holding an approved make-up / trial for the date
 * (#672, see `bulk-attendance-error.ts`). That stays true — this predicate
 * only stops the count from PROMISING the coach a number the server was
 * always going to refuse, for the two cases the roster already spells out on
 * screen:
 *
 * - an on-hold seat (#697/#773 — the row renders an "ON HOLD" chip, and a
 *   held or mid-reclaim enrollment is not active, so the server refuses it);
 * - a parent-submitted absence notice for this occurrence — the parent has
 *   already said the student isn't coming, so "mark everyone else present"
 *   should not sweep them in.
 *
 * Deliberately a deny-list, not an `=== "active"` allow-list: one-time
 * make-up / trial rows carry no standing enrollment status, and a status this
 * client doesn't know about must not silently vanish from the batch. Anything
 * not named here — a paused seat, a hold placed since the roster was fetched
 * — is left to the existing post-rejection retry, which remains the fallback
 * authority. Both kinds of row stay tappable one at a time; only the bulk
 * batch skips them.
 *
 * Pure function in the node vitest environment — no React, no fetch.
 */

export interface BulkMarkableRosterEntry {
  /** Absent/null on one-time (make-up / trial) rows: they have no enrollment. */
  enrollment_status?: string | null;
  /** True when a parent filed an absence notice for this occurrence. */
  expected_absence?: boolean;
}

/** Enrollment states the roster shows as "ON HOLD" and the server refuses. */
const HELD_STATUSES: ReadonlySet<string> = new Set(["held", "reclaim_pending"]);

export function isBulkMarkEligible(student: BulkMarkableRosterEntry): boolean {
  if (student.enrollment_status && HELD_STATUSES.has(student.enrollment_status)) return false;
  return student.expected_absence !== true;
}
