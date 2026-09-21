"use client";

import { useState } from "react";
import { MoreVertical } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { Button, Card, Chip, Overline, PhoneList, PhoneListRow } from "@/components/ds";
import { OverflowMenu, type MenuItem } from "@/components/ds/menu";
import { useIsPhone } from "@/lib/use-is-phone";
import { getAdminInvoiceDetail } from "@/lib/api/admin";
import type { FamilyInvoice, InvoiceAction } from "@/lib/api/admin-families";
import { queryKeys } from "@/lib/query/keys";
import { invoiceStatusChip } from "@/lib/billing-status";
import { formatCents, formatInstantDay } from "@/lib/money";

import { invoiceActionLabel, periodLabel, shortDate } from "./family-view";

/**
 * #890: the row used to render EVERY entry of `inv.actions`, so void, refund,
 * one-time discount and charge-card-now sat on the row AND in "Fix something" —
 * the same money action with two homes, and an open invoice carrying five
 * buttons in ragged lines. The row now keeps only the two actions that are
 * genuinely row-specific and offered nowhere else, in this fixed order;
 * "Fix something" is the single home for the other four.
 *
 * #857: these stay DIRECT buttons — `invoice-action-<action>-<id>` is clicked
 * by id in `admin-family-billing.spec.ts` — and each clears 44px on a phone.
 */
const ROW_DIRECT_ACTIONS: InvoiceAction[] = ["record_payment", "send"];

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
  onAddCharge,
  onCreateInvoice,
  onFullAudit,
}: {
  invoices: FamilyInvoice[];
  busy: boolean;
  onAction: (action: InvoiceAction, invoice: FamilyInvoice) => void;
  onAddCharge: (invoice: FamilyInvoice) => void;
  onCreateInvoice: () => void;
  onFullAudit: (invoice: FamilyInvoice) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const isPhone = useIsPhone();

  /**
   * Anything row-specific beyond those two goes behind a More menu (#890), so
   * the row never grows a third and fourth direct button. Reached in specs
   * through `e2e/helpers/row-actions.ts`, which finds menu items by label. The
   * trigger is deliberately `invoice-more-<id>` and NOT the row's own
   * `invoice-row-<id>` prefix, so a prefix match for rows never picks it up.
   */
  function invoiceMenuItems(inv: FamilyInvoice): MenuItem[] {
    if (inv.status !== "draft") return [];
    return [
      {
        key: "add_charge",
        label: "Add charge",
        disabled: busy,
        onSelect: () => onAddCharge(inv),
      },
    ];
  }

  function invoiceActions(inv: FamilyInvoice, phone: boolean) {
    const buttonClass = phone ? "min-h-touch" : undefined;
    const rowLabel = `${periodLabel(inv.period)}${inv.student_name ? ` · ${inv.student_name}` : ""}`;
    const menuItems = invoiceMenuItems(inv);
    return (
      <>
        {ROW_DIRECT_ACTIONS.filter((a) => inv.actions.includes(a)).map((a) => (
          <Button
            key={a}
            size="sm"
            variant="secondary"
            className={buttonClass}
            data-testid={`invoice-action-${a}-${inv.invoice_id}`}
            onClick={() => onAction(a, inv)}
            disabled={busy}
          >
            {invoiceActionLabel(a)}
          </Button>
        ))}
        {menuItems.length > 0 && (
          <OverflowMenu
            className="shrink-0"
            items={menuItems}
            triggerLabel={`More actions for ${rowLabel}`}
            triggerTestId={`invoice-more-${inv.invoice_id}`}
            trigger={
              <span className="flex min-h-touch min-w-touch items-center justify-center rounded-md text-rally-muted hover:bg-rally-paper">
                <MoreVertical className="size-5" aria-hidden="true" />
              </span>
            }
          />
        )}
      </>
    );
  }

  function expandedDetail(inv: FamilyInvoice) {
    return (
      <div
        className="mt-2 rounded-lg bg-rally-paper px-3 py-2 text-xs"
        data-testid={`invoice-allocations-${inv.invoice_id}`}
      >
        {inv.settlement_unlinked && <p className="text-rally-muted">paid (no payment record)</p>}
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
        {inv.allocations.length === 0 && inv.credits.length === 0 && !inv.settlement_unlinked && (
          <p className="text-rally-muted">No payments applied.</p>
        )}
        <InvoiceLines invoiceId={inv.invoice_id} />
        <button
          type="button"
          className="mt-1 min-h-touch text-rally-cobalt-700 hover:underline"
          data-testid={`invoice-audit-${inv.invoice_id}`}
          onClick={() => onFullAudit(inv)}
        >
          Full audit
        </button>
      </div>
    );
  }

  if (isPhone) {
    return (
      <Card p={20} data-testid="family-invoices">
        <div className="flex items-center justify-between">
          <Overline>Invoices</Overline>
          <Button
            size="sm"
            variant="secondary"
            className="min-h-touch"
            data-testid="family-create-invoice"
            onClick={onCreateInvoice}
            disabled={busy}
          >
            Create invoice
          </Button>
        </div>
        {invoices.length === 0 ? (
          <p className="mt-2 text-sm text-rally-muted">No invoices yet.</p>
        ) : (
          <PhoneList className="mt-2" aria-label="Invoices">
            {invoices.map((inv) => {
              const chip = invoiceStatusChip(inv.status);
              const expanded = openId === inv.invoice_id;
              return (
                <PhoneListRow
                  key={inv.invoice_id}
                  data-testid={`invoice-row-${inv.invoice_id}`}
                  title={
                    <button
                      type="button"
                      data-testid={`invoice-expand-${inv.invoice_id}`}
                      aria-expanded={expanded}
                      onClick={() => setOpenId(expanded ? null : inv.invoice_id)}
                      className="min-h-touch text-left font-semibold text-rally-ink hover:underline"
                    >
                      {expanded ? "▾" : "▸"} {periodLabel(inv.period)}
                      {inv.student_name ? ` · ${inv.student_name}` : ""}
                    </button>
                  }
                  primary={
                    <span className="font-mono text-sm font-semibold tabular-nums text-rally-ink">
                      {formatCents(inv.total_cents)}
                    </span>
                  }
                  secondary={
                    <>
                      <div className="flex flex-wrap items-center gap-2">
                        <Chip variant={chip.variant} label={chip.label} />
                        {inv.due_date && inv.balance_due_cents > 0 && (
                          <span>due {shortDate(inv.due_date)}</span>
                        )}
                        {inv.invoice_number && <span>{inv.invoice_number}</span>}
                      </div>
                      <div>
                        {inv.balance_due_cents > 0
                          ? `${formatCents(inv.balance_due_cents)} due`
                          : "Nothing due"}
                        {inv.paid_cents > 0 && inv.status !== "paid"
                          ? ` · ${formatCents(inv.paid_cents)} paid`
                          : ""}
                      </div>
                      <div>{deliveryLabel(inv)}</div>
                      <div className="flex flex-wrap gap-2 pt-1">{invoiceActions(inv, true)}</div>
                      {expanded && expandedDetail(inv)}
                    </>
                  }
                />
              );
            })}
          </PhoneList>
        )}
      </Card>
    );
  }

  return (
    <Card p={20} data-testid="family-invoices">
      <div className="flex items-center justify-between">
        <Overline>Invoices</Overline>
        <Button
          size="sm"
          variant="secondary"
          data-testid="family-create-invoice"
          onClick={onCreateInvoice}
          disabled={busy}
        >
          Create invoice
        </Button>
      </div>
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
                    {invoiceActions(inv, false)}
                  </span>
                </div>
                {expanded && expandedDetail(inv)}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/**
 * What the invoice is made of. Lines are the only place a discount, a fee or an
 * added charge is visible to an admin, so the ledger view keeps them (the
 * billing surface inventory lists lines alongside allocations and credits for
 * the panel this page absorbs). Fetched on expand rather than with the family
 * so the page stays one request.
 */
function InvoiceLines({ invoiceId }: { invoiceId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.invoiceDetail(invoiceId),
    queryFn: () => getAdminInvoiceDetail(invoiceId),
  });

  if (isLoading) {
    return <p className="mt-1 text-rally-muted">Loading charges…</p>;
  }
  if (isError || !data) {
    return <p className="mt-1 text-rally-muted">Charges unavailable.</p>;
  }
  const lines = data.lines ?? [];
  if (lines.length === 0) {
    return null;
  }
  return (
    <div className="mt-1" data-testid={`invoice-lines-${invoiceId}`}>
      {lines.map((line, i) => (
        <p key={line.line_id ?? `${line.description}-${i}`}>
          · {line.description}
          {line.line_type ? ` (${line.line_type})` : ""} — {formatCents(line.amount_cents)}
        </p>
      ))}
    </div>
  );
}
