"use client";

import { Button, Card, Overline } from "@/components/ds";
import type {
  FamilyInvoice,
  FamilyManualPayment,
  InvoiceAction,
} from "@/lib/api/admin-families";

import { manualPaymentSummary } from "./family-view";

type FixKind = Extract<InvoiceAction, "void" | "refund" | "discount_once" | "charge_card">;

type FixItem = { kind: FixKind; label: string; ownerOnly: boolean };

// Every fix here moves money, so all are owner-only (staff tiers, roadmap
// 2026-09-22 section 6 item 2). Card charges joined in #928; the backend also
// 404s a non-owner on both charge routes and strips `charge_card` from their
// invoice actions, so this is presentation, not the gate.
const ITEMS: FixItem[] = [
  { kind: "void", label: "Void invoice", ownerOnly: true },
  { kind: "refund", label: "Refund", ownerOnly: true },
  { kind: "discount_once", label: "One-time discount", ownerOnly: true },
  { kind: "charge_card", label: "Charge card now", ownerOnly: true },
];

export function fixItemsFor(isOwner: boolean): FixItem[] {
  return ITEMS.filter((it) => isOwner || !it.ownerOnly);
}

export function FixSomethingPanel({
  invoices,
  manualPayments = [],
  isOwner,
  onPick,
  onVoidPayment,
}: {
  invoices: FamilyInvoice[];
  manualPayments?: FamilyManualPayment[];
  isOwner: boolean;
  onPick: (kind: FixKind, invoiceId: string) => void;
  onVoidPayment: (payment: FamilyManualPayment) => void;
}) {
  const items = fixItemsFor(isOwner);
  // A plain admin has nothing to fix here (#928), so the panel is not shown.
  if (items.length === 0) return null;
  return (
    <Card p={20} data-testid="family-fix">
      <Overline>Fix something</Overline>
      <p className="mt-1 text-xs text-rally-muted">
        Every action asks for a reason and lands in the timeline.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {items.map((it) => {
          const targets = invoices.filter((inv) => inv.actions.includes(it.kind));
          return (
            <div key={it.kind} className="rounded-lg border border-rally-line p-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-rally-ink">{it.label}</span>
                <span className="text-xs text-rally-muted">{targets.length} eligible</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {targets.slice(0, 4).map((inv) => (
                  <Button
                    key={inv.invoice_id}
                    size="sm"
                    variant="secondary"
                    data-testid={`fix-${it.kind}-${inv.invoice_id}`}
                    onClick={() => onPick(it.kind, inv.invoice_id)}
                  >
                    {inv.period}
                    {inv.student_name ? ` · ${inv.student_name}` : ""}
                  </Button>
                ))}
                {targets.length === 0 && (
                  <span className="text-xs text-rally-muted">nothing eligible</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {/* #890's "Undo manual payment" placeholder, now real. Owner-only like
          the rest; the void route also refuses anyone else. */}
      {isOwner && (
        <ManualPaymentsList payments={manualPayments} invoices={invoices} onVoid={onVoidPayment} />
      )}
    </Card>
  );
}

/**
 * Cash/check/Zelle/... payments that settled this family's invoices. Voiding
 * one is how a payment entered by mistake comes off the books: the invoices
 * stay (they are real charges) and reopen, and any credit it minted is
 * cancelled. Stripe money is never listed; it is refunded instead.
 */
function ManualPaymentsList({
  payments,
  invoices,
  onVoid,
}: {
  payments: FamilyManualPayment[];
  invoices: FamilyInvoice[];
  onVoid: (payment: FamilyManualPayment) => void;
}) {
  return (
    <div
      className="mt-3 rounded-lg border border-rally-line p-2"
      data-testid="family-manual-payments"
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-rally-ink">Void a manual payment</span>
        <span className="text-xs text-rally-muted">{payments.length} recorded</span>
      </div>
      <p className="mt-1 text-xs text-rally-muted">
        For a cash, check or Zelle payment entered by mistake. This voids the payment, not an
        invoice: the invoices stay and their balances reopen.
      </p>
      {payments.length === 0 ? (
        <span className="mt-1 block text-xs text-rally-muted">nothing eligible</span>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {payments.map((p) => {
            const summary = manualPaymentSummary(p, invoices);
            return (
              <li
                key={p.payment_id}
                className="flex flex-wrap items-start justify-between gap-2 py-2"
                data-testid={`manual-payment-${p.payment_id}`}
              >
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-rally-ink">{summary.title}</div>
                  <div className="text-xs text-rally-muted">{summary.detail}</div>
                  {summary.blocked && (
                    <div className="mt-1 text-xs text-rally-ink">{summary.blocked}</div>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={summary.blocked !== null}
                  data-testid={`void-payment-${p.payment_id}`}
                  onClick={() => onVoid(p)}
                >
                  Void payment
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
