"use client";

/**
 * S57 "YOU OWE" card (docs/design/parent-money.md §3.1–3.4). Renders the
 * backend summary as is: no amount on this card is computed in the browser.
 */
import type { ReactNode } from "react";

import { BigNum, Button, Card } from "@/components/ds";
import type { ParentMoneySummary } from "@/lib/api/parent";
import { formatPlainDate } from "@/lib/format/plain-date";
import { dueLine, formatMoney, showFamilyTotal } from "@/lib/parent/money-summary";

const ACCENT = { overdue: "#dc2626", due: "#2563eb", clear: "#059669" } as const;

export function MoneySummaryCard({
  summary,
  todayIso,
  hasInvoices,
  onPay,
  payPending,
  paySettling,
  paymentInstructions,
  payExtras,
}: {
  summary: ParentMoneySummary;
  todayIso: string;
  hasInvoices: boolean;
  onPay: () => void;
  payPending: boolean;
  paySettling: boolean;
  paymentInstructions?: string | null;
  /** The existing autopay opt-in, rendered under the Pay button. */
  payExtras?: ReactNode;
}) {
  const currency = summary.currency;
  const due = summary.amount_due_cents > 0;
  const figure = formatMoney(summary.amount_due_cents, currency);
  const date = dueLine(summary, todayIso);
  const accent = !due ? ACCENT.clear : summary.overdue ? ACCENT.overdue : ACCENT.due;
  const spoken = date ? `You owe ${figure}, ${date.toLowerCase()}` : `You owe ${figure}`;
  return (
    <section aria-labelledby="money-summary-heading" data-testid="money-summary">
      <Card p={16} accent={accent}>
        {/* Overline look on a real heading (a <div> may not sit inside an <h2>). */}
        <h2
          id="money-summary-heading"
          tabIndex={-1}
          className="font-mono text-[10px] font-bold uppercase tracking-overline text-status-slate-700 outline-none"
        >
          You owe
        </h2>
        <div className="mt-1 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div aria-label={spoken} role="group">
            <BigNum size={36}>
              <span data-testid="money-summary-amount">{figure}</span>
            </BigNum>
            {date && (
              <p
                data-testid="money-summary-due"
                className={`mt-1 text-sm ${summary.overdue ? "font-semibold text-status-red-800" : "text-rally-ink"}`}
              >
                {date}
                {summary.overdue && (
                  <span className="ml-2 rounded-full bg-status-red-50 px-2 py-0.5 text-xs font-semibold uppercase text-status-red-800">
                    Overdue
                  </span>
                )}
              </p>
            )}
            {!due && (
              <p data-testid="money-summary-clear" className="mt-1 text-sm text-rally-ink">
                {hasInvoices
                  ? "Nothing to pay right now."
                  : "No invoices yet. Your first invoice appears here when the academy sends it."}
              </p>
            )}
            {!due && summary.last_payment && (
              <p data-testid="money-summary-last-payment" className="mt-1 text-xs text-rally-subtle">
                Last payment: {formatMoney(summary.last_payment.amount_cents, currency)}
                {summary.last_payment.paid_on
                  ? ` on ${formatPlainDate(summary.last_payment.paid_on, { month: "short", day: "numeric" })}`
                  : ""}
                , {summary.last_payment.method_label.toLowerCase()}.
              </p>
            )}
          </div>
          {due && summary.can_pay_online && (
            <div className="lg:w-56">
              <Button
                type="button"
                data-testid="pay-balance"
                variant="primary"
                size="lg"
                full
                onClick={onPay}
                disabled={payPending || paySettling}
                className="rounded-xl disabled:opacity-60"
              >
                {paySettling ? "Processing…" : payPending ? "Starting…" : `Pay ${figure}`}
              </Button>
              <p className="mt-2 text-xs text-rally-subtle" data-testid="pay-balance-reassurance">
                Secure checkout via Stripe
              </p>
              {payExtras}
            </div>
          )}
        </div>
        {due && summary.lines.length > 0 && (
          <dl data-testid="money-summary-lines" className="mt-3 space-y-2 border-t border-rally-line pt-3">
            {summary.lines.map((line) => {
              const amount = formatMoney(Math.abs(line.amount_cents), currency);
              const negative = line.amount_cents < 0;
              return (
                <div
                  key={`${line.kind}-${line.student_id ?? line.label}`}
                  data-testid={`money-line-${line.kind}`}
                  className="flex items-start justify-between gap-3 text-sm"
                >
                  <dt className="min-w-0">
                    <span className={line.kind === "child" ? "font-medium text-rally-ink" : "text-rally-ink"}>
                      {line.label}
                    </span>
                    {line.detail && <span className="block text-xs text-rally-subtle">{line.detail}</span>}
                  </dt>
                  <dd
                    className={`shrink-0 tabular-nums ${line.kind === "discount" ? "text-status-green-800" : "text-rally-ink"}`}
                    aria-label={negative ? `minus ${amount}` : amount}
                  >
                    {negative ? `−${amount}` : amount}
                  </dd>
                </div>
              );
            })}
            {showFamilyTotal(summary) && (
              <div
                data-testid="money-summary-total"
                className="flex items-center justify-between gap-3 border-t border-rally-line pt-2 text-sm font-semibold text-rally-ink"
              >
                <dt>Total for your family</dt>
                <dd className="tabular-nums">{figure}</dd>
              </div>
            )}
          </dl>
        )}
        {due && !summary.can_pay_online && (
          <div data-testid="money-summary-how-to-pay" className="mt-3 rounded-lg border border-rally-line p-3 text-sm">
            <p className="font-medium text-rally-ink">How to pay</p>
            {paymentInstructions && (
              <p className="mt-1 whitespace-pre-line text-xs text-rally-muted">{paymentInstructions}</p>
            )}
            <p className="mt-1 text-xs text-rally-subtle">
              Tell the front desk when you have paid so they can mark it.
            </p>
          </div>
        )}
      </Card>
    </section>
  );
}
