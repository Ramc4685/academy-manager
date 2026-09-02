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
