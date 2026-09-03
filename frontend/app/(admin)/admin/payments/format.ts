import type { AdminPaymentStatus, AdminPaymentView } from "@/lib/api/admin";
import type { ChipVariant } from "@/components/ds/chip";

export function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function skipReasonLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export function finalCents(payment: AdminPaymentView): number {
  return payment.final_amount_cents ?? Math.max(payment.amount_cents - payment.discount_cents, 0);
}

export function paymentDisplayLabel(payment: AdminPaymentView): string {
  if (payment.period) return `Tuition for ${payment.period}`;
  return payment.stripe_linked ? "Stripe payment" : "Manual payment";
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

export const STATUS_CHIP: Record<AdminPaymentStatus, PaymentStatusChip> = {
  succeeded: { variant: "paid", label: "PAID" },
  paid: { variant: "paid", label: "PAID" },
  pending: { variant: "pending", label: "PENDING" },
  partially_paid: { variant: "partial", label: "PARTIAL" },
  refunded: { variant: "refunded", label: "REFUNDED" },
  partially_refunded: { variant: "partial", label: "PARTIAL" },
  failed: { variant: "failed", label: "FAILED" },
  expired: { variant: "expired", label: "EXPIRED" },
  waived: { variant: "waived", label: "WAIVED" },
};

export function statusChip(status: string | null | undefined): PaymentStatusChip {
  if (status && status in STATUS_CHIP) {
    return STATUS_CHIP[status as AdminPaymentStatus];
  }
  return {
    variant: "pending",
    label: (status || "unknown").replaceAll("_", " ").toUpperCase(),
  };
}

/** Human label for a settlement method: every `stripe_*` variant reads as "Stripe". */
export function paymentMethodLabel(method: string | null | undefined): string | null {
  if (!method) return null;
  if (method.startsWith("stripe")) return "STRIPE";
  return method.replaceAll("_", " ").toUpperCase();
}

export function methodChip(payment: AdminPaymentView): { variant: ChipVariant; label: string } | null {
  const isStripe = payment.stripe_linked || Boolean(payment.payment_method?.startsWith("stripe"));
  if (isStripe) return { variant: "autopayOn", label: "STRIPE" };
  const label = paymentMethodLabel(payment.payment_method);
  return label ? { variant: "manual", label } : null;
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

export function reconciliationLabel(payment: AdminPaymentView): string | null {
  if (payment.reconciliation_status) {
    return payment.reconciliation_status.replaceAll("_", " ");
  }
  if (
    (payment.status === "pending" || payment.status === "partially_paid") &&
    payment.stripe_linked
  ) {
    return "Stripe linked, app ledger pending";
  }
  return null;
}

export function isLedgerInvoiceRow(payment: AdminPaymentView): boolean {
  return payment.payment_method === "invoice" || payment.payment_method === "stripe";
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

export const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "partially_paid", label: "Partially paid" },
  { value: "paid", label: "Paid" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "refunded", label: "Refunded" },
  { value: "partially_refunded", label: "Partially refunded" },
  { value: "expired", label: "Expired" },
  { value: "waived", label: "Waived" },
];
