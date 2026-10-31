/**
 * Last resort only: a session with no zone of its own AND no academy zone.
 * A class always runs on its academy's clock, so rendering in UTC (a 6pm
 * Chicago class as 11pm) is a visible defect, never a real answer.
 */
export const LAST_RESORT_TIMEZONE = "UTC";

/** The zone to render a session in: session zone, then academy zone, then UTC. */
export function sessionTimezone(
  timezone: string | null | undefined,
  academyTimezone?: string | null,
): string {
  return timezone?.trim() || academyTimezone?.trim() || LAST_RESORT_TIMEZONE;
}

export function formatSessionTimeRange(
  start: string,
  end: string,
  timezone?: string | null,
  academyTimezone?: string | null,
): string {
  const timeZone = sessionTimezone(timezone, academyTimezone);
  const fmt = (value: string) =>
    parseSessionInstant(value).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone,
    });
  return `${fmt(start)} – ${fmt(end)}`;
}

export function sessionDateKey(
  iso: string,
  timezone?: string | null,
  academyTimezone?: string | null,
): string {
  const timeZone = sessionTimezone(timezone, academyTimezone);
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(parseSessionInstant(iso));
  const part = (type: string) => parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function parseSessionInstant(value: string): Date {
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(value)) {
    return new Date(value);
  }
  return new Date(`${value}Z`);
}
