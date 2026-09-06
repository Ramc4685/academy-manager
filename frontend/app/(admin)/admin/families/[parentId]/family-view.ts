/** Pure view helpers for the Family billing page; no React, no fetch. */
import type { ChipVariant } from "@/components/ds/chip";
import type {
  FamilyAutopay,
  InvoiceAction,
  RegistrationState,
  TimelineKind,
} from "@/lib/api/admin-families";

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

export interface RegistrationChip {
  label: string;
  variant: ChipVariant;
}

/** Maps registration state onto the DS Chip's real variants (paid=green, pending=amber, manual=slate). */
export function registrationChip(state: RegistrationState): RegistrationChip {
  if (state === "registered") return { label: "Card on file", variant: "paid" };
  if (state === "invited") return { label: "Invited", variant: "pending" };
  return { label: "Not invited", variant: "manual" };
}

export type TimelineTone = "muted" | TimelineKind;

export function timelineTone(entry: { kind: TimelineKind; muted: boolean }): TimelineTone {
  return entry.muted ? "muted" : entry.kind;
}

export function mintRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}`;
}
