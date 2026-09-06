"use client";

import { useState } from "react";

import { Button, Card, Chip, Overline } from "@/components/ds";
import type { FamilyInvoice, InvoiceAction } from "@/lib/api/admin-families";
import { invoiceStatusChip } from "@/lib/billing-status";
import { formatCents, formatInstantDay } from "@/lib/money";

import { invoiceActionLabel, periodLabel, shortDate } from "./family-view";

function deliveryLabel(inv: FamilyInvoice): string {
  if (inv.delivery.last_sent_at) {
    const what = inv.delivery.kind === "autopay_notice" ? "notice" : "invoice";
    return `${what} emailed ${shortDate(inv.delivery.last_sent_at)}`;
  }
  if (inv.status === "void") return inv.void_reason ?? "voided";
  return "not sent";
}

export function InvoicesPanel({
  invoices,
  busy,
  onAction,
  onFullAudit,
}: {
  invoices: FamilyInvoice[];
  busy: boolean;
  onAction: (action: InvoiceAction, invoice: FamilyInvoice) => void;
  onFullAudit: (invoice: FamilyInvoice) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <Card p={20} data-testid="family-invoices">
      <Overline>Invoices</Overline>
      {invoices.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">No invoices yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {invoices.map((inv) => {
            const chip = invoiceStatusChip(inv.status);
            const expanded = openId === inv.invoice_id;
            return (
              <li
                key={inv.invoice_id}
                data-testid={`invoice-row-${inv.invoice_id}`}
                className="py-2 text-sm"
              >
                <div className="grid gap-1 md:grid-cols-[minmax(0,1fr)_auto_auto_minmax(0,1fr)] md:items-center md:gap-4">
                  <button
                    type="button"
                    data-testid={`invoice-expand-${inv.invoice_id}`}
                    aria-expanded={expanded}
                    onClick={() => setOpenId(expanded ? null : inv.invoice_id)}
                    className="text-left font-semibold text-rally-ink hover:underline"
                  >
                    {expanded ? "▾" : "▸"} {periodLabel(inv.period)}
                    {inv.student_name ? ` · ${inv.student_name}` : ""}
                    <span className="ml-1 text-xs font-normal text-rally-muted">
                      {inv.invoice_number ?? ""}
                    </span>
                  </button>
                  <span className="text-rally-ink">
                    {formatCents(inv.total_cents)}
                    {inv.paid_cents > 0 && inv.status !== "paid" && (
                      <span className="text-xs text-rally-muted">
                        {" "}
                        · {formatCents(inv.paid_cents)} paid
                      </span>
                    )}
                    {inv.balance_due_cents > 0 && (
                      <span className="text-xs text-rally-muted">
                        {" "}
                        · {formatCents(inv.balance_due_cents)} due
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-2">
                    <Chip variant={chip.variant} label={chip.label} />
                    {inv.due_date && inv.balance_due_cents > 0 && (
                      <span className="text-xs text-rally-muted">due {shortDate(inv.due_date)}</span>
                    )}
                  </span>
                  <span className="flex flex-wrap items-center justify-end gap-1">
                    <span className="mr-2 text-xs text-rally-muted">{deliveryLabel(inv)}</span>
                    {inv.actions.map((a) => (
                      <Button
                        key={a}
                        size="sm"
                        variant={a === "void" || a === "refund" ? "danger" : "secondary"}
                        data-testid={`invoice-action-${a}-${inv.invoice_id}`}
                        onClick={() => onAction(a, inv)}
                        disabled={busy}
                      >
                        {invoiceActionLabel(a)}
                      </Button>
                    ))}
                  </span>
                </div>
                {expanded && (
                  <div
                    className="mt-2 rounded-lg bg-rally-paper px-3 py-2 text-xs"
                    data-testid={`invoice-allocations-${inv.invoice_id}`}
                  >
                    {inv.settlement_unlinked && (
                      <p className="text-rally-muted">paid (no payment record)</p>
                    )}
                    {inv.allocations.map((a) => (
                      <p key={`${a.payment_id}-${a.amount_cents}`}>
                        ↳ {formatCents(a.amount_cents)} · {a.method ?? "payment"} ·{" "}
                        {formatInstantDay(a.paid_at)}
                        {a.stripe_payment_intent_id ? ` · ${a.stripe_payment_intent_id}` : ""}
                      </p>
                    ))}
                    {inv.credits.map((c) => (
                      <p key={c.credit_id}>↳ credit {formatCents(c.amount_cents)}</p>
                    ))}
                    {inv.allocations.length === 0 &&
                      inv.credits.length === 0 &&
                      !inv.settlement_unlinked && (
                        <p className="text-rally-muted">No payments applied.</p>
                      )}
                    <button
                      type="button"
                      className="mt-1 text-rally-cobalt-700 hover:underline"
                      data-testid={`invoice-audit-${inv.invoice_id}`}
                      onClick={() => onFullAudit(inv)}
                    >
                      Full audit
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
