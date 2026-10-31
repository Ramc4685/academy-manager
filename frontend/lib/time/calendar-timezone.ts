/**
 * Which clock the coach/parent calendar grid runs on (#1043).
 *
 * FullCalendar renders in the browser's zone by default, so a 6:00 PM
 * Chicago class showed as "4p" to a coach in Los Angeles — and near midnight
 * on the wrong day — while every detail screen said 6:00 PM CDT. The grid
 * must run on the same academy/session zone as those screens, through
 * FullCalendar's named-zone plugin (real DST rules, no fixed offsets).
 *
 * When no trustworthy zone is known the calendar must say so instead of
 * quietly falling back to the browser clock — hence the explicit
 * `unavailable` state rather than a default zone.
 *
 * Pure functions in the node vitest environment — no React, no DOM.
 */

import { isValidTimeZone, parseAcademyInstant } from "@/lib/format/academy-time";

export type CalendarTimeZone =
  | { status: "ready"; timeZone: string }
  | { status: "unavailable" };

/**
 * The single zone a calendar grid renders in, from the zones its classes run
 * on (coach: each schedule entry's `timezone`, which the BFF already fills
 * with the academy zone; parent: the academy's `timezone`).
 *
 * Blank and invalid names are ignored. When several valid zones appear the
 * most common wins (ties: first seen) — the grid can only show one clock and
 * labels it; every event is still placed at its true instant in that zone.
 * No valid zone at all → `unavailable`, never the browser zone.
 */
export function resolveCalendarTimeZone(
  candidates: ReadonlyArray<string | null | undefined>,
): CalendarTimeZone {
  const counts = new Map<string, number>();
  for (const raw of candidates) {
    const tz = raw?.trim();
    if (!tz || !isValidTimeZone(tz)) continue;
    counts.set(tz, (counts.get(tz) ?? 0) + 1);
  }
  let best: string | null = null;
  let bestCount = 0;
  for (const [tz, count] of counts) {
    if (count > bestCount) {
      best = tz;
      bestCount = count;
    }
  }
  return best ? { status: "ready", timeZone: best } : { status: "unavailable" };
}

/**
 * An explicit UTC instant for FullCalendar.
 *
 * With a named `timeZone`, FullCalendar reads an offset-less string as wall
 * time IN that zone, while the backend's naive timestamps are UTC (the same
 * rule `sessionDateKey` and the academy formatters apply). Pinning the
 * offset keeps the grid, the link date and the detail screens on one instant.
 */
export function calendarInstant(iso: string): string {
  const instant = parseAcademyInstant(iso);
  return Number.isNaN(instant.getTime()) ? iso : instant.toISOString();
}

/**
 * "Times in Central Time (America/Chicago)" — the grid's visible clock label.
 *
 * Uses the generic zone name, not "CDT"/"CST": the grid pages across DST
 * changes and one abbreviation would be wrong for half the year.
 */
export function calendarTimeZoneLabel(timeZone: string): string {
  let generic: string | undefined;
  try {
    generic = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longGeneric" })
      .formatToParts(new Date(0))
      .find((p) => p.type === "timeZoneName")?.value;
  } catch {
    generic = undefined;
  }
  return generic && generic !== timeZone
    ? `Times in ${generic} (${timeZone})`
    : `Times in ${timeZone}`;
}
