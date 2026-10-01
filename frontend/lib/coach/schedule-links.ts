/**
 * Coach schedule → links and calendar events (#1043, #1045).
 *
 * The session screen is occurrence-scoped and asks `/coach/today` for the
 * class's LOCAL date (the backend buckets occurrences by session-local day,
 * #510). Sessions, Calendar and Today must therefore all build the link from
 * `sessionDateKey`, never from the UTC date in `start_at` — an evening class
 * in Chicago is already "tomorrow" in UTC and opened "Session not found."
 *
 * Pure functions in the node vitest environment — no React, no fetch.
 */

import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import type { CoachScheduleEntry } from "@/lib/api/coach";
import { coachSessionHref } from "@/lib/coach/marking";
import { isValidTimeZone } from "@/lib/format/academy-time";
import {
  calendarInstant,
  resolveCalendarTimeZone,
  type CalendarTimeZone,
} from "@/lib/time/calendar-timezone";
import { sessionDateKey } from "@/lib/time/session-time";

type LinkableEntry = Pick<CoachScheduleEntry, "occurrence_id" | "start_at" | "timezone">;

/**
 * Detail link for one schedule entry, dated on the class's own clock.
 *
 * `fallbackTimeZone` is the academy zone to use when the entry carries none
 * (the calendar passes its grid zone), so a zone-less class links to the same
 * local date the grid shows it on instead of the UTC date.
 */
export function coachScheduleEntryHref(
  entry: LinkableEntry,
  fallbackTimeZone?: string | null,
): string {
  return coachSessionHref(
    entry.occurrence_id,
    sessionDateKey(entry.start_at, entry.timezone, fallbackTimeZone),
  );
}

/**
 * The coach calendar's events and the zone its grid runs on — the session
 * zone every coach detail screen already formats in (the BFF fills it with
 * the academy zone for sessions that carry none).
 */
export function coachScheduleToCalendar(entries: readonly CoachScheduleEntry[]): {
  timeZone: CalendarTimeZone;
  events: CalendarViewEvent[];
} {
  const timeZone = resolveCalendarTimeZone(entries.map((e) => e.timezone));
  const gridZone = timeZone.status === "ready" ? timeZone.timeZone : null;
  return {
    timeZone,
    events: entries.map((s) => ({
      id: s.occurrence_id,
      title: s.title,
      start: calendarInstant(s.start_at),
      end: calendarInstant(s.end_at),
      // A corrupt zone name would make Intl throw; such an entry gets no
      // link instead of taking the whole calendar down.
      url: !s.timezone?.trim() || isValidTimeZone(s.timezone.trim())
        ? coachScheduleEntryHref(s, gridZone)
        : undefined,
    })),
  };
}
