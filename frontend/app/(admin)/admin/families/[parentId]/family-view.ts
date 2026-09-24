/** Pure view helpers for the Family billing page; no React, no fetch. */
import type { ChipVariant } from "@/components/ds/chip";
import type {
  FamilyAutopay,
  FamilyEmailDelivery,
  FamilyEnrollment,
  FamilyHeader,
  FamilyInvoice,
  FamilyStudent,
  InvoiceAction,
  RegistrationState,
  TimelineKind,
} from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";
import {
  cardChip,
  cardStateFromRegistration,
  loginChip,
  loginStateFromRegistration,
  type PeopleChip,
} from "@/lib/people-status";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-08" → "Sep 8" without a timezone shift (dates are academy-local already). */
export function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d || m < 1 || m > 12) return null;
  return `${MONTHS[m - 1]} ${d}`;
}

/** "2026-09" → "Sep 2026"; anything else is echoed back. */
export function periodLabel(period: string): string {
  const [y, m] = period.split("-").map(Number);
  return y && m && m >= 1 && m <= 12 ? `${MONTHS[m - 1]} ${y}` : period;
}

export interface ToggleProps {
  checked: boolean;
  disabled: boolean;
  label: string;
  hint: string;
}

export function autopayToggle(a: FamilyAutopay): ToggleProps {
  const card = a.card_last4 ? `${a.card_label ?? "Card"} ••${a.card_last4}` : "no card on file";
  const next = a.next_charge_on ? ` · next charge ${shortDate(a.next_charge_on)}` : "";
  switch (a.state) {
    case "on":
      return { checked: true, disabled: false, label: "On", hint: `${card}${next}` };
    case "partial":
      return {
        checked: true,
        disabled: false,
        label: `On for ${a.active_count} of ${a.total_count}`,
        hint: `${card}${next}`,
      };
    case "off":
      return { checked: false, disabled: false, label: "Off", hint: card };
    case "needs_consent":
    default:
      return {
        checked: false,
        disabled: true,
        label: "Off",
        hint: "Needs parent consent — send invite",
      };
  }
}

const INVOICE_ACTION_LABELS: Record<InvoiceAction, string> = {
  send: "Send invoice",
  record_payment: "Record payment",
  charge_card: "Charge card now",
  void: "Void invoice",
  refund: "Refund",
  discount_once: "One-time discount",
};

export function invoiceActionLabel(action: InvoiceAction): string {
  return INVOICE_ACTION_LABELS[action];
}

/**
 * #929: "$25.00 refunded · $35.00 net" when anything came back, else null.
 * `net` is the backend's figure when it sent one; otherwise paid minus refunded.
 */
export function refundLabel(
  paidCents: number,
  refundedCents: number | null | undefined,
  netCents?: number | null,
): string | null {
  const refunded = refundedCents ?? 0;
  if (refunded <= 0) return null;
  const net = netCents ?? Math.max(paidCents - refunded, 0);
  return `${formatCents(refunded)} refunded · ${formatCents(net)} net`;
}

export function invoiceRefundLabel(inv: FamilyInvoice): string | null {
  return refundLabel(inv.paid_cents, inv.refunded_cents, inv.net_paid_cents);
}

/** #929 family totals line: "Paid $70.00 · $50.00 refunded · $20.00 net", or null. */
export function familyRefundLine(header: FamilyHeader): string | null {
  const paid = header.paid_cents ?? 0;
  const label = refundLabel(paid, header.refunded_cents, header.net_paid_cents);
  return label ? `Paid ${formatCents(paid)} · ${label}` : null;
}

/**
 * Card money on this invoice not yet given back: the Refund dialog's ceiling.
 * Before #929 this ignored earlier refunds, so a second refund offered the
 * full card amount again.
 */
export function refundableCents(inv: FamilyInvoice): number {
  const card = inv.allocations
    .filter((a) => a.stripe_payment_intent_id)
    .reduce((s, a) => s + a.amount_cents, 0);
  return Math.max(card - (inv.refunded_cents ?? 0), 0);
}

export interface RegistrationChips {
  login: PeopleChip;
  card: PeopleChip;
}

/**
 * Registration is really two facts — can they log in, and can we charge them.
 * #840: both take their wording from `lib/people-status`, the one map the
 * families list and the Users page read too, so the pages cannot drift.
 */
export function registrationChips(state: RegistrationState): RegistrationChips {
  return {
    login: loginChip(loginStateFromRegistration(state)),
    card: cardChip(cardStateFromRegistration(state)),
  };
}

export interface UndeliverableChip {
  label: string;
  variant: ChipVariant;
  detail: string;
}

/**
 * #778: the suppression list has known these addresses were dead since #556,
 * but nothing admin-facing said so — the family was invoiced, dunned and
 * eventually dropped in silence.
 *
 * A hard bounce blocks everything including invoices, so it is a red chip and
 * an instruction. A complaint only blocks digests and news, so it says that
 * instead of frightening an admin into chasing a working address.
 */
export function undeliverableChip(
  delivery: FamilyEmailDelivery | undefined | null,
): UndeliverableChip | null {
  if (!delivery?.undeliverable || !delivery.since) return null;
  const day = shortDate(delivery.since) ?? "an earlier date";
  const address = delivery.email ?? "this address";
  if (delivery.reason === "complaint") {
    return {
      label: `Marked as spam on ${day}`,
      variant: "pending",
      detail: `${address} reported our email as spam, so summaries and news are blocked. Invoices still send.`,
    };
  }
  return {
    label: `Email undeliverable since ${day}`,
    variant: "failed",
    detail: `Nothing we send reaches ${address}. Ask for a new address.`,
  };
}

export type TimelineTone = "muted" | TimelineKind;

export function timelineTone(entry: { kind: TimelineKind; muted: boolean }): TimelineTone {
  return entry.muted ? "muted" : entry.kind;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Today's month in the viewer's own calendar, as the API's "YYYY-MM". */
export function currentPeriod(today: Date = new Date()): string {
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}`;
}

/**
 * Fallback window, matching the backend's BillingSettings default. Only used
 * while the Billing-rules query is in flight or unavailable.
 */
export const DEFAULT_INVOICE_DUE_DAYS = 7;

/**
 * The academy's "Days until due" Billing rule (#739). A configured 0 means due
 * today, so only a missing schedule falls back — never `||`.
 */
export function invoiceDueDays(
  schedule: { invoice_due_days: number } | null | undefined,
): number {
  return schedule?.invoice_due_days ?? DEFAULT_INVOICE_DUE_DAYS;
}

/** Default invoice due date: the configured window out, as the API's "YYYY-MM-DD". */
export function defaultDueDate(
  today: Date = new Date(),
  days: number = DEFAULT_INVOICE_DUE_DAYS,
): string {
  const due = new Date(today.getFullYear(), today.getMonth(), today.getDate() + days);
  return `${due.getFullYear()}-${pad(due.getMonth() + 1)}-${pad(due.getDate())}`;
}

/**
 * Must match the monthly generator's wording (`_tuition_line_description` in
 * mongo_monthly_billing.py) so a hand-made tuition line reads like a generated
 * one on the invoice and in the parent's email.
 */
export function tuitionLineDescription(period: string): string {
  return `Monthly tuition ${period}`;
}

/** What this enrollment is billed per month, override first; null when unpriced. */
export function enrollmentPriceCents(enrollment: FamilyEnrollment): number | null {
  return enrollment.override_price_cents ?? enrollment.monthly_price_cents ?? null;
}

export interface EnrollmentOption {
  enrollment_id: string;
  student_id: string;
  student_name: string;
  label: string;
  price_cents: number | null;
}

/** Flattens the family's students into one pickable list of enrollments. */
export function enrollmentOptions(students: FamilyStudent[]): EnrollmentOption[] {
  return students.flatMap((student) =>
    student.enrollments.map((enrollment) => ({
      enrollment_id: enrollment.enrollment_id,
      student_id: student.student_id,
      student_name: student.name,
      label: `${student.name} · ${enrollment.session_title ?? "Class"}`,
      price_cents: enrollmentPriceCents(enrollment),
    })),
  );
}

export function mintRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}`;
}
