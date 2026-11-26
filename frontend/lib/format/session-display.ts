/**
 * Display helpers for session/occurrence rows returned by the API.
 *
 * These live outside the page components because getting them wrong is not a
 * cosmetic bug: the parent onboarding "Review & pay" screen rendered a real
 * 6:00 PM CDT class as "1:00 PM" (browser zone, no `timeZone` passed), telling
 * a parent the wrong hour on the screen where they commit to paying.
 *
 * Rule: a session timestamp is a UTC instant and MUST be rendered in the zone
 * the class actually runs in — the session's own `timezone`, falling back to
 * the academy's. The viewer's browser zone is the last resort and is always
 * made visible by the trailing zone label ("CDT", "GMT+5:30").
 */

import { formatAcademyDateTime, formatAcademyTimeRange } from "./academy-time";

export interface SessionTimeFields {
  start_at: string;
  end_at: string;
  timezone?: string | null;
}

/**
 * Resolve the zone to render a session in: the session's own zone wins, then
 * the academy's. `null` lets the formatter fall back to the browser zone with
 * a visible label.
 */
export function sessionDisplayZone(
  session: Pick<SessionTimeFields, "timezone">,
  academyTimezone: string | null | undefined,
): string | null {
  return session.timezone?.trim() || academyTimezone?.trim() || null;
}

/** "Thu, Sep 3 · 6:00 PM – 6:45 PM CDT" for a catalog/occurrence row. */
export function formatSessionOccurrence(
  session: SessionTimeFields,
  academyTimezone: string | null | undefined,
): string {
  return formatAcademyTimeRange(
    session.start_at,
    session.end_at,
    sessionDisplayZone(session, academyTimezone),
  );
}

/** "Thu, Sep 3 · 6:00 PM CDT" for a single timestamp (e.g. a quote expiry). */
export function formatAcademyMoment(
  iso: string,
  academyTimezone: string | null | undefined,
): string {
  return formatAcademyDateTime(iso, academyTimezone ?? null);
}

export interface WeeklyPatternFields {
  days_of_week?: string[] | null;
  start_time?: string | null;
  end_time?: string | null;
}

const WEEKDAY_PLURAL: Record<string, string> = {
  mon: "Mondays",
  tue: "Tuesdays",
  wed: "Wednesdays",
  thu: "Thursdays",
  fri: "Fridays",
  sat: "Saturdays",
  sun: "Sundays",
};

function wallClock(value: string): { text: string; meridiem: "AM" | "PM" } | null {
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  if (!match || Number(match[1]) > 23) return null;
  const hour = Number(match[1]);
  return { text: `${hour % 12 || 12}:${match[2]}`, meridiem: hour < 12 ? "AM" : "PM" };
}

/**
 * S27: a weekly class's pattern, "Saturdays 9:00–10:00 AM" or
 * "Mon & Wed 4:30–5:30 PM". The class's first dated start is not its schedule:
 * shown on its own it reads as a one-off date that has already passed.
 * Returns "" when the class has no weekly pattern.
 */
export function formatWeeklyPattern(session: WeeklyPatternFields): string {
  const days = (session.days_of_week ?? []).map((d) => d.trim()).filter(Boolean);
  if (days.length === 0) return "";
  const key = (d: string) => d.toLowerCase().slice(0, 3);
  const shortDay = (d: string) => d.charAt(0).toUpperCase() + d.slice(1, 3).toLowerCase();
  const dayText =
    days.length === 1
      ? WEEKDAY_PLURAL[key(days[0])] ?? days[0]
      : `${days
          .slice(0, -1)
          .map(shortDay)
          .join(", ")} & ${shortDay(days[days.length - 1])}`;
  const start = session.start_time ? wallClock(session.start_time) : null;
  const end = session.end_time ? wallClock(session.end_time) : null;
  if (!start) return dayText;
  if (!end) return `${dayText} ${start.text} ${start.meridiem}`;
  const startText = start.meridiem === end.meridiem ? start.text : `${start.text} ${start.meridiem}`;
  return `${dayText} ${startText}–${end.text} ${end.meridiem}`;
}
