/**
 * Parent-facing copy for an enrollment the child has already left (issue #775).
 *
 * Terminal enrollments used to be excluded from every parent read, so a family
 * that left logged in to a child card with no history at all. The parent
 * enrollments feed now carries the most recent departure per child, tagged
 * `departed`. These helpers turn that row into a line the family can read.
 *
 * A departed row is HISTORY, never money: callers must not offer cancel,
 * autopay or payment controls on it.
 */

export interface DepartableEnrollment {
  departed?: boolean;
  left_on?: string | null;
  departure_reason?: string | null;
}

export function isDepartedEnrollment(enrollment: DepartableEnrollment): boolean {
  return enrollment.departed === true;
}

/**
 * "Ended Jun 1, 2026", or plain "Ended" when the row carries no date.
 *
 * `formatDate` is injected so the caller can format the instant in the
 * academy's timezone without this module importing the time helpers.
 */
export function departureLabel(
  leftOn: string | null | undefined,
  formatDate: (iso: string) => string,
): string {
  const day = leftOn ? formatDate(leftOn) : "";
  return day ? `Ended ${day}` : "Ended";
}

/** The recorded reason, trimmed; null when the row has none worth printing. */
export function departureReasonNote(reason: string | null | undefined): string | null {
  const trimmed = reason?.trim();
  return trimmed ? `Reason given: ${trimmed}` : null;
}
