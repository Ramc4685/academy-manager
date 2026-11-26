/**
 * S57 wording for the Payments summary (docs/design/parent-money.md §5).
 * Words only: every amount comes from GET /parent/money-summary.
 */
import type { ParentMoneySummary } from "@/lib/api/parent";
import { formatPlainDate } from "@/lib/format/plain-date";

export function formatMoney(cents: number, currency = "usd"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(
    cents / 100,
  );
}

/** "Due Tue, Dec 1" / "Due today" / "Was due Sun, Nov 1 · 25 days ago" / "First payment due …". */
export function dueLine(summary: ParentMoneySummary, todayIso: string): string | null {
  if (summary.amount_due_cents <= 0 || !summary.due_date) return null;
  const date = formatPlainDate(summary.due_date);
  if (summary.overdue) {
    const days = summary.days_overdue === 1 ? "1 day ago" : `${summary.days_overdue} days ago`;
    return `Was due ${date} · ${days}`;
  }
  if (summary.due_date === todayIso) return "Due today";
  return summary.multiple_due_dates ? `First payment due ${date}` : `Due ${date}`;
}

/** Shown for 2+ child lines or any discount/paid line; one plain child needs no total. */
export function showFamilyTotal(summary: ParentMoneySummary): boolean {
  const children = summary.lines.filter((line) => line.kind === "child").length;
  return children > 1 || summary.lines.some((line) => line.kind !== "child");
}

const PAYMENT_STATUS_WORDS: Record<string, string> = {
  succeeded: "Paid",
  paid: "Paid",
  pending: "Processing",
  processing: "Processing",
  failed: "Did not go through",
  refunded: "Refunded",
  partially_refunded: "Partly refunded",
  voided: "Cancelled",
};

/** Plain words for a payment status; never the raw "succeeded". */
export function paymentStatusWord(status: string): string {
  return PAYMENT_STATUS_WORDS[status] ?? status.replace(/_/g, " ");
}

export function creditCopy(cents: number, currency = "usd"): string {
  return `${formatMoney(cents, currency)} credit on your account. It comes off your next invoice.`;
}
