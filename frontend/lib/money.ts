/**
 * The one money formatter. Every page that shows a dollar amount should call
 * `formatCents` instead of keeping a local Intl.NumberFormat copy (payments
 * buckets spec, docs/superpowers/specs/2026-09-05-payments-buckets-design.md).
 */

const CENTS_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const WHOLE_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/** "$1,110.00"; with `{ whole: true }` → "$1,110". */
export function formatCents(cents: number, opts?: { whole?: boolean }): string {
  const dollars = cents / 100;
  return opts?.whole ? WHOLE_FORMATTER.format(dollars) : CENTS_FORMATTER.format(dollars);
}

const DATE_ONLY_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * "Sep 8, 2026" from a calendar-date string ("2026-09-08"), "—" when empty.
 *
 * The backend sends due dates, charge dates and resume dates as plain
 * YYYY-MM-DD values that already carry the academy's calendar day, so this
 * formats the date exactly as written and never shifts it by the viewer's
 * timezone. A full ISO datetime is accepted and truncated to its date part.
 */
export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return "—";
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (Number.isNaN(date.getTime())) return "—";
  return DATE_ONLY_FORMATTER.format(date);
}
