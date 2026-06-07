const DEFAULT_SESSION_TIMEZONE = "UTC";

export function sessionTimezone(timezone: string | null | undefined): string {
  return timezone?.trim() || DEFAULT_SESSION_TIMEZONE;
}

export function formatSessionTimeRange(
  start: string,
  end: string,
  timezone?: string | null,
): string {
  const timeZone = sessionTimezone(timezone);
  const fmt = (value: string) =>
    parseSessionInstant(value).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone,
    });
  return `${fmt(start)} – ${fmt(end)}`;
}

export function sessionDateKey(iso: string, timezone?: string | null): string {
  const timeZone = sessionTimezone(timezone);
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
