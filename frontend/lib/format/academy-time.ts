/**
 * Academy-timezone timestamp formatting.
 *
 * Schedule/occurrence timestamps must render in the ACADEMY's timezone, not
 * the viewer's browser timezone (a parent traveling abroad should still see
 * "Thu 6:00 PM CDT" for a Chicago academy class). Every formatter here
 * appends an explicit short timezone label (e.g. "CDT") so that when the
 * academy timezone is unavailable and we fall back to the browser timezone,
 * the fallback is visible rather than silent.
 */

interface ResolvedZone {
  timeZone: string;
  usedFallback: boolean;
}

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/**
 * Resolve the timezone to format in. Uses the academy timezone when present
 * and valid; otherwise falls back to the viewer's browser timezone.
 */
export function resolveAcademyTimeZone(
  academyTimezone: string | null | undefined,
): ResolvedZone {
  const tz = academyTimezone?.trim();
  if (tz && isValidTimeZone(tz)) {
    return { timeZone: tz, usedFallback: false };
  }
  return { timeZone: browserTimeZone(), usedFallback: true };
}

/** Parse an ISO timestamp; naive strings (no offset) are treated as UTC. */
export function parseAcademyInstant(value: string): Date {
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(value)) {
    return new Date(value);
  }
  return new Date(`${value}Z`);
}

/** Short timezone label (e.g. "CDT", "GMT+5:30") for an instant in a zone. */
export function academyTimeZoneLabel(instant: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    timeZoneName: "short",
  }).formatToParts(instant);
  return parts.find((p) => p.type === "timeZoneName")?.value ?? timeZone;
}

function formatTime(instant: Date, timeZone: string): string {
  return instant.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
}

function formatDayDate(instant: Date, timeZone: string): string {
  return instant.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone,
  });
}

/**
 * "Thu, Jul 2 · 6:00 PM CDT" — a single timestamp in the academy timezone
 * with an explicit tz label.
 */
export function formatAcademyDateTime(
  iso: string,
  academyTimezone: string | null | undefined,
): string {
  const instant = parseAcademyInstant(iso);
  if (Number.isNaN(instant.getTime())) return "";
  const { timeZone } = resolveAcademyTimeZone(academyTimezone);
  const label = academyTimeZoneLabel(instant, timeZone);
  return `${formatDayDate(instant, timeZone)} · ${formatTime(instant, timeZone)} ${label}`;
}

/**
 * "Thu, Jul 2 · 6:00 PM – 6:45 PM CDT" — an occurrence range in the academy
 * timezone with an explicit tz label.
 */
export function formatAcademyTimeRange(
  startIso: string,
  endIso: string,
  academyTimezone: string | null | undefined,
): string {
  const start = parseAcademyInstant(startIso);
  const end = parseAcademyInstant(endIso);
  if (Number.isNaN(start.getTime())) return "";
  const { timeZone } = resolveAcademyTimeZone(academyTimezone);
  const label = academyTimeZoneLabel(start, timeZone);
  const startTime = formatTime(start, timeZone);
  const endTime = Number.isNaN(end.getTime()) ? "" : formatTime(end, timeZone);
  const range = endTime ? `${startTime} – ${endTime}` : startTime;
  return `${formatDayDate(start, timeZone)} · ${range} ${label}`;
}

/**
 * "Thu, Jul 2" — a date in the academy timezone (no time, no label). Using
 * the academy zone avoids off-by-one-day dates for viewers in other zones.
 */
export function formatAcademyDate(
  iso: string,
  academyTimezone: string | null | undefined,
): string {
  const instant = parseAcademyInstant(iso);
  if (Number.isNaN(instant.getTime())) return "";
  const { timeZone } = resolveAcademyTimeZone(academyTimezone);
  return formatDayDate(instant, timeZone);
}
