"use client";

import { Button, Card, Overline } from "@/components/ds";
import type { FamilyInvoice, InvoiceAction } from "@/lib/api/admin-families";

import { DisabledFixItem } from "./family-dialogs";

type FixKind = Extract<InvoiceAction, "void" | "refund" | "discount_once" | "charge_card">;

const ITEMS: { kind: FixKind; label: string; ownerOnly: boolean }[] = [
  { kind: "void", label: "Void invoice", ownerOnly: true },
  { kind: "refund", label: "Refund", ownerOnly: true },
  { kind: "discount_once", label: "One-time discount", ownerOnly: true },
  { kind: "charge_card", label: "Charge card now", ownerOnly: false },
];

export function FixSomethingPanel({
  invoices,
  isOwner,
  onPick,
}: {
  invoices: FamilyInvoice[];
  isOwner: boolean;
  onPick: (kind: FixKind, invoiceId: string) => void;
}) {
  return (
    <Card p={20} data-testid="family-fix">
      <Overline>Fix something</Overline>
      <p className="mt-1 text-xs text-rally-muted">
        Every action asks for a reason and lands in the timeline.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {ITEMS.filter((it) => isOwner || !it.ownerOnly).map((it) => {
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
        <DisabledFixItem label="Account credit" hint="coming later" />
        <DisabledFixItem label="Undo manual payment" hint="coming later" />
      </div>
    </Card>
  );
}
