import type { AdminPaymentStatus, AdminPaymentView } from "@/lib/api/admin";
import type { ChipVariant } from "@/components/ds/chip";
import { INVOICE_STATUS_FILTER_OPTIONS, invoiceStatusChip } from "@/lib/billing-status";

export { formatCents } from "@/lib/money";

export function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * #892: a period is money wording, not a key. The list, the table, the refund
 * dialog and the skipped-deferral list all said "2026-09"; an admin reading a
 * refund has to recognise the month at a glance. Anything that is not a
 * `YYYY-MM` key is handed back untouched so a period never silently vanishes.
 */
export function formatPeriodLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})$/.exec(value.trim());
  if (!match) return value;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (month < 1 || month > 12) return value;
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * #892: the skipped-deferral list printed the raw code ("skipped by admin",
 * "enrollment paused"). These are the codes `MonthlyGenerationSkippedDetail`
 * carries — the deferral types plus the three the monthly run stamps itself.
 * An unknown code still reads as a sentence rather than throwing, because the
 * backend can add one without the UI shipping again.
 */
const SKIP_REASON_LABELS: Readonly<Record<string, string>> = {
  skipped_by_admin: "Skipped this month",
  legacy_skip_period: "Skipped this month",
  manual_skip: "Skipped by hand",
  enrollment_paused: "Enrollment paused",
  pending_cancellation: "Leaving at the end of the period",
  admin_hold: "On hold",
  admin_pause: "Paused by the academy",
  fixed_pause: "Paused until a set date",
  stale_pause: "Pause needs review",
  capacity_blocked_resume: "Class is full, cannot resume",
  active_stripe_subscription_mismatch: "Subscription does not match",
};

export function skipReasonLabel(value: string): string {
  const known = SKIP_REASON_LABELS[value];
  if (known) return known;
  const words = value.replaceAll("_", " ").trim();
  if (!words) return value;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function finalCents(payment: AdminPaymentView): number {
  return payment.final_amount_cents ?? Math.max(payment.amount_cents - payment.discount_cents, 0);
}

export function paymentDisplayLabel(payment: AdminPaymentView): string {
  if (payment.period) return `Tuition for ${formatPeriodLabel(payment.period)}`;
  return payment.stripe_linked ? "Stripe payment" : "Manual payment";
}

/**
 * UI-5: the title a row carries in the invoices list. The list already shows
 * the period in its own column (desktop) or on its own line (phone), so the
 * row title does not repeat it: a month of tuition used to print "Tuition for
 * September 2026" on every row and wrap to three lines. Dialogs and action
 * menus keep `paymentDisplayLabel`, where the month is the only context.
 */
export function paymentRowTitle(payment: AdminPaymentView): string {
  if (payment.period) return "Monthly tuition";
  return paymentDisplayLabel(payment);
}

export function paidCents(payment: AdminPaymentView): number | null {
  if (payment.paid_amount_cents > 0) return Math.max(payment.paid_amount_cents - payment.refunded_cents, 0);
  if (!["succeeded", "paid", "partially_refunded", "refunded"].includes(payment.status)) return null;
  return Math.max(finalCents(payment) - payment.refunded_cents, 0);
}

export function adminPaymentStatus(payment: AdminPaymentView): string {
  return payment.status as AdminPaymentStatus;
}

export type PaymentStatusChip = { variant: ChipVariant; label: string };

/**
 * Status chip for an invoice/payment row, in the one UI vocabulary
 * (draft / open / partially paid / paid / void) — see lib/billing-status.ts.
 */
export function statusChip(status: string | null | undefined): PaymentStatusChip {
  return invoiceStatusChip(status);
}

/**
 * Human label for a settlement method. Every `stripe_*` variant
 * (stripe_checkout, stripe_autopay, stripe_subscription, stripe_legacy) MUST
 * read as "Stripe" — the backend stamps the specific variant on ledger rows
 * and the admin UI is expected to show one consistent label (PR #645).
 */
export function paymentMethodLabel(method: string | null | undefined): string | null {
  if (!method) return null;
  if (method.startsWith("stripe")) return "STRIPE";
  return method.replaceAll("_", " ").toUpperCase();
}

/**
 * Method chip. The real settlement method wins: an invoice can carry a Stripe
 * invoice id (stripe_linked) and still have been paid by Zelle or cash, and
 * that manual method must not be relabelled "Stripe". stripe_linked is only a
 * fallback when the row has no method beyond the "invoice" placeholder.
 */
export function methodChip(payment: AdminPaymentView): { variant: ChipVariant; label: string } | null {
  const method = payment.payment_method && payment.payment_method !== "invoice" ? payment.payment_method : null;
  if (method) {
    const label = paymentMethodLabel(method);
    if (!label) return null;
    return label === "STRIPE" ? { variant: "autopayOn", label } : { variant: "manual", label };
  }
  if (payment.stripe_linked) return { variant: "autopayOn", label: "STRIPE" };
  return null;
}

export function stripeIdSummary(payment: AdminPaymentView): string | null {
  const ids = [
    payment.stripe_checkout_session_id,
    payment.stripe_invoice_id,
    payment.stripe_payment_intent_id,
    payment.stripe_subscription_id,
  ].filter(Boolean);
  if (ids.length === 0) return null;
  return ids.join(" · ");
}

/**
 * UI-5: the row annotation used to print the backend code with underscores
 * swapped for spaces ("stripe synced", "orphan charge", "missing allocation")
 * and "Stripe linked, app ledger pending" — developer strings an admin cannot
 * act on. Each code now reads as a sentence that says what happened and, when
 * something needs a person, where to go. `stripe_synced` is the healthy state
 * and gets no annotation at all: it was the same amber note on every paid
 * Stripe row. Unknown codes (a card decline code, a new backend value) still
 * read as a sentence rather than a raw key.
 */
const RECONCILIATION_LABELS: Readonly<Record<string, string | null>> = {
  stripe_synced: null,
  stripe_linked_pending: "Waiting for Stripe to confirm this payment",
  payment_failed: "The last payment attempt failed",
  missing_allocation: "Payment received but not matched to this invoice. Check Billing Health.",
  orphan_charge: "Stripe took a payment that is not matched to an invoice. Check Billing Health.",
  card_declined: "The last payment attempt failed: card declined",
  insufficient_funds: "The last payment attempt failed: not enough funds",
  expired_card: "The last payment attempt failed: card expired",
  incorrect_cvc: "The last payment attempt failed: wrong security code",
  processing_error: "The last payment attempt failed: the card processor had an error",
  authentication_required: "The last payment attempt failed: the bank asked the family to confirm",
  unknown: "The last payment attempt failed",
};

export function reconciliationStatusLabel(code: string): string | null {
  if (Object.prototype.hasOwnProperty.call(RECONCILIATION_LABELS, code)) {
    return RECONCILIATION_LABELS[code] ?? null;
  }
  const words = code.replaceAll("_", " ").trim();
  if (!words) return null;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function reconciliationLabel(payment: AdminPaymentView): string | null {
  if (payment.reconciliation_status) {
    return reconciliationStatusLabel(payment.reconciliation_status);
  }
  if (
    (payment.status === "pending" || payment.status === "partially_paid") &&
    payment.stripe_linked
  ) {
    return RECONCILIATION_LABELS.stripe_linked_pending ?? null;
  }
  return null;
}

/**
 * Invoice rows are keyed by their invoice id (payment_id === invoice_id). Do
 * NOT key this off payment_method: since PR #645 an invoice row carries the
 * method it was settled with (stripe_checkout, zelle, ...), so a method check
 * would hide invoice actions on every paid invoice.
 */
export function isLedgerInvoiceRow(payment: AdminPaymentView): boolean {
  return Boolean(payment.invoice_id) && payment.payment_id === payment.invoice_id;
}

export function invoiceActionId(payment: AdminPaymentView | null): string {
  return payment?.invoice_id || payment?.payment_id || "";
}

export function sessionFilterKey(payment: AdminPaymentView): string {
  return payment.session_id || "__none__";
}

export function sessionFilterLabel(value: string): string {
  return value === "__none__" ? "No session" : value;
}

export const PAGE_SIZE = 50;

/**
 * Status filter in the chip vocabulary (draft / open / partially paid / paid /
 * void). Applied client-side via `matchesInvoiceStatusFilter` because the
 * backend list filter is an exact raw-status match and the list still emits
 * raw statuses such as `succeeded` that render as PAID.
 */
export const STATUS_FILTER_OPTIONS: readonly { value: string; label: string }[] =
  INVOICE_STATUS_FILTER_OPTIONS;
