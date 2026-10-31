/**
 * Calendar-date formatting (issue #841).
 *
 * Some values are dates with no instant attached — a parent's preferred trial
 * window is "2026-07-15", a day on a calendar, not a moment in time. Running
 * those through `formatAcademyDateTime` would invent a midnight UTC instant
 * and then shift it into a timezone, which is how "Jul 15" becomes "Jul 14"
 * for an admin in Chicago. These helpers format the date as written.
 */

const PLAIN_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "Wed, Jul 15" — a `YYYY-MM-DD` date. Anything else is returned unchanged. */
export function formatPlainDate(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  const match = PLAIN_DATE.exec(raw);
  if (!match) return raw;
  const instant = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(instant.getTime())) return raw;
  return instant.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * "Wed, Jul 15 – Wed, Jul 22" for a preferred window. A single-day window
 * collapses to one date, a half-filled one shows the end it has, and an empty
 * one reads as an em dash rather than " – ".
 */
export function formatPlainDateRange(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const from = formatPlainDate(start);
  const to = formatPlainDate(end);
  if (from && to) return from === to ? from : `${from} – ${to}`;
  return from || to || "—";
}
