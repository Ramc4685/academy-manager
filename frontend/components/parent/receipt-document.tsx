"use client";

/**
 * S58: a paid invoice as a printable receipt (docs/design/parent-money.md §3.6).
 * Modelled on signed-waiver-document.tsx: printing prints only this card.
 * Every amount and date is the backend's.
 */
import { AcademyMark } from "@/components/ds/academy-mark";
import { Button } from "@/components/ds/button";
import type { ParentReceipt } from "@/lib/api/parent";
import { formatPlainDate } from "@/lib/format/plain-date";
import { formatMoney } from "@/lib/parent/money-summary";
import { useIsNativeApp } from "@/lib/use-native-app";

const LONG_DATE: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" };

export function ReceiptDocument({
  receipt,
  print = () => window.print(),
}: {
  receipt: ParentReceipt;
  print?: () => void;
}) {
  const isNativeApp = useIsNativeApp();
  const money = (cents: number) =>
    cents < 0 ? `−${formatMoney(-cents, receipt.currency)}` : formatMoney(cents, receipt.currency);
  const contact = [receipt.academy.phone, receipt.academy.email].filter(Boolean).join(" · ");
  return (
    <div className="space-y-4">
      {!isNativeApp && (
        <div className="flex justify-end print:hidden">
          <Button type="button" variant="secondary" onClick={print}>
            Print or save as PDF
          </Button>
        </div>
      )}
      <article
        data-testid="receipt-document"
        className="receipt-print space-y-5 rounded-2xl border border-rally-line bg-white p-6 text-sm leading-6 text-rally-ink"
      >
        <header className="flex items-start gap-3">
          <AcademyMark name={receipt.academy.name} logoUrl={receipt.academy.logo_url ?? null} size={40} />
          <div className="min-w-0">
            <h1 className="font-display text-xl font-semibold">{receipt.academy.name}</h1>
            {receipt.academy.address && <p className="text-rally-muted">{receipt.academy.address}</p>}
            {contact && <p className="text-rally-muted">{contact}</p>}
          </div>
        </header>

        <section className="space-y-1">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="font-display text-base font-semibold uppercase tracking-wide">Receipt</h2>
            {receipt.invoice_number && <span className="font-mono text-xs">{receipt.invoice_number}</span>}
          </div>
          {receipt.paid_in_full_on && (
            <p data-testid="receipt-paid-on">Paid in full on {formatPlainDate(receipt.paid_in_full_on, LONG_DATE)}</p>
          )}
        </section>

        <dl className="grid grid-cols-[6rem_1fr] gap-y-1">
          <dt className="text-rally-muted">Paid by</dt>
          <dd>{receipt.payer_name || "Not recorded"}</dd>
          <dt className="text-rally-muted">For</dt>
          <dd>{receipt.student_name || "Family"}</dd>
          <dt className="text-rally-muted">Period</dt>
          <dd>{receipt.period_label}</dd>
        </dl>

        <dl className="space-y-1 border-t border-rally-line pt-3">
          {receipt.lines.map((line, index) => (
            <div key={`${line.label}-${index}`} className="flex justify-between gap-3">
              <dt>{line.label}</dt>
              <dd className="tabular-nums">{money(line.amount_cents)}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-3 border-t border-rally-line pt-2 font-semibold">
            <dt>Total</dt>
            <dd className="tabular-nums" data-testid="receipt-total">{money(receipt.total_cents)}</dd>
          </div>
        </dl>

        <section className="space-y-1 border-t border-rally-line pt-3">
          <h3 className="font-semibold">Payments</h3>
          <ul className="space-y-1">
            {receipt.payments.map((payment, index) => (
              <li key={`${payment.paid_on}-${index}`} className="flex justify-between gap-3">
                <span>
                  {payment.paid_on ? formatPlainDate(payment.paid_on, LONG_DATE) : "Date not recorded"} · {payment.method}
                </span>
                <span className="tabular-nums">{money(payment.amount_cents)}</span>
              </li>
            ))}
          </ul>
          <div className="flex justify-between gap-3 font-semibold">
            <span>Balance</span>
            <span className="tabular-nums">{money(receipt.balance_cents)}</span>
          </div>
        </section>

        <p className="text-[11px] text-status-slate-700">
          This receipt was produced by {receipt.academy.name} using CourtMastr.
        </p>
      </article>
      <style>{PRINT_CSS}</style>
    </div>
  );
}

// Print only the receipt: the shell, nav and buttons stay off the paper.
const PRINT_CSS = `
@media print {
  @page { size: auto portrait; margin: 12mm; }
  html, body { background: #fff !important; }
  body * { visibility: hidden !important; }
  .receipt-print, .receipt-print * { visibility: visible !important; color: #000 !important; }
  .receipt-print { position: absolute !important; left: 0; top: 0; width: 100%; border: 0 !important; font-size: 12pt; }
}
`;
