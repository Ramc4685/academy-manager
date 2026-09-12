/**
 * Parent-facing copy for an enrollment on hold (issue #740).
 *
 * A hold (#697) keeps the child's seat but stops attendance, so the class
 * produces no upcoming sessions. Filtering held rows out of the parent UI —
 * which is what the portal used to do — made the class simply disappear: the
 * family saw fewer classes and no reason. These helpers give the row a state
 * and a return date instead.
 *
 * `hold_return_on` is a CALENDAR date ("2026-10-15"), not an instant: it must
 * read as the same day everywhere, so it is never run through the
 * academy-timezone instant formatters.
 */

export interface HoldableEnrollment {
  status: string;
  hold_return_on?: string | null;
  session_title?: string;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isHeldEnrollment(enrollment: { status: string }): boolean {
  return enrollment.status === "held";
}

/** Split a child's enrollments into the ones still running and the held ones. */
export function partitionByHold<T extends { status: string }>(
  enrollments: T[],
): { active: T[]; held: T[] } {
  return {
    active: enrollments.filter((e) => e.status === "active"),
    held: enrollments.filter(isHeldEnrollment),
  };
}

/** "Oct 15, 2026" for a plain ISO date; "" when it is missing or malformed. */
export function formatHoldDate(holdReturnOn: string | null | undefined): string {
  const match = holdReturnOn?.trim().match(ISO_DATE);
  if (!match) return "";
  const [, year, month, day] = match;
  const instant = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (Number.isNaN(instant.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(instant);
}

/** Badge label for a held enrollment row. */
export function holdReturnLabel(holdReturnOn: string | null | undefined): string {
  const day = formatHoldDate(holdReturnOn);
  return day ? `On hold until ${day}` : "On hold";
}

/**
 * Sentence explaining an empty "Upcoming sessions" list, or null when the
 * emptiness has nothing to do with a hold.
 */
export function holdScheduleNote(enrollments: HoldableEnrollment[]): string | null {
  const held = enrollments.filter(isHeldEnrollment);
  if (held.length === 0) return null;
  const subject =
    held.length === 1 && held[0].session_title ? held[0].session_title : "This class";
  const soonest = held
    .map((e) => e.hold_return_on)
    .filter((d): d is string => Boolean(d && ISO_DATE.test(d)))
    .sort()[0];
  const day = formatHoldDate(soonest);
  return day
    ? `${subject} is on hold — classes resume ${day}.`
    : `${subject} is on hold.`;
}
