/**
 * Presentation rules for the Billing Health header.
 *
 * The verdict itself is computed on the backend (spec 2026-09-07 §4.2) — the
 * page used to derive "System healthy" from backlog counts alone and could
 * render a green pill directly above a red "Parents cannot pay right now"
 * card. All that is left on this side is the state → tone mapping and the
 * truncation line, kept here so they can be tested without a browser.
 */

export type BillingHealthState = "blocked" | "attention" | "ok";

export interface HealthPill {
  /** Data attribute the e2e specs assert on. */
  tone: "red" | "amber" | "green";
  className: string;
}

const PILLS: Record<BillingHealthState, HealthPill> = {
  blocked: { tone: "red", className: "bg-red-50 text-red-700" },
  attention: { tone: "amber", className: "bg-amber-50 text-amber-800" },
  ok: { tone: "green", className: "bg-green-50 text-green-700" },
};

/**
 * Tone for a verdict state. An unrecognised state reads as `attention`, never
 * as healthy: a state we cannot interpret is not a state we can call fine.
 */
export function healthPillTone(state: string | null | undefined): HealthPill {
  if (state && state in PILLS) return PILLS[state as BillingHealthState];
  return PILLS.attention;
}

/**
 * "Showing the 50 most recent of 214 quarantined events." — the webhook list
 * route caps at 50 while the tile beside it shows the true aggregate count, so
 * say so rather than letting the two silently disagree.
 */
export function truncationLine(shown: number, total: number): string | null {
  if (total <= shown) return null;
  return `Showing the ${shown} most recent of ${total} quarantined events.`;
}

/**
 * #892: Stripe's own event names ("invoice.payment_failed") and invoice status
 * keys ("past_due") were printed straight onto Billing Health and the Payments
 * recovery queue. The issue's acceptance criterion is that neither screen shows
 * a raw id or a snake_case status by default, so both read as sentences here
 * and the raw string stays one disclosure away for support.
 *
 * Anything unmapped is humanised rather than dropped: the backend can forward a
 * new Stripe event type without the UI shipping again.
 */
const WEBHOOK_EVENT_LABELS: Readonly<Record<string, string>> = {
  "checkout.session.completed": "Checkout completed",
  "checkout.session.async_payment_failed": "Bank payment failed",
  "checkout.session.async_payment_succeeded": "Bank payment cleared",
  "invoice.paid": "Invoice paid",
  "invoice.payment_failed": "Invoice payment failed",
  "invoice.payment_succeeded": "Invoice payment succeeded",
  "payment_intent.succeeded": "Payment succeeded",
  "payment_intent.payment_failed": "Payment failed",
  "charge.refunded": "Charge refunded",
  "customer.subscription.deleted": "Subscription cancelled",
  "customer.subscription.updated": "Subscription updated",
};

function humanise(value: string): string {
  const words = value.replaceAll(".", " ").replaceAll("_", " ").trim();
  if (!words) return value;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "invoice.payment_failed" → "Invoice payment failed". */
export function webhookEventLabel(value: string | null | undefined): string {
  if (!value) return "Unknown event";
  return WEBHOOK_EVENT_LABELS[value] ?? humanise(value);
}

const INVOICE_STATUS_LABELS: Readonly<Record<string, string>> = {
  draft: "a draft",
  open: "open",
  paid: "paid",
  partially_paid: "partly paid",
  past_due: "past due",
  uncollectible: "written off",
  void: "voided",
  refunded: "refunded",
  pending: "pending",
};

/**
 * Invoice status as a sentence fragment ("past due"), never the stored key
 * ("past_due"). Used in the reconciliation link confirmation.
 */
export function invoiceStatusLabel(value: string | null | undefined): string {
  if (!value) return "updated";
  return INVOICE_STATUS_LABELS[value] ?? value.replaceAll("_", " ");
}
