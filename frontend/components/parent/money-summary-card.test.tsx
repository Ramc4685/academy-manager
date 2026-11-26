import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ParentMoneySummary } from "@/lib/api/parent";
import { MoneySummaryCard } from "./money-summary-card";

const due: ParentMoneySummary = {
  currency: "usd",
  amount_due_cents: 14000,
  due_date: "2026-12-01",
  overdue: false,
  days_overdue: 0,
  multiple_due_dates: false,
  can_pay_online: true,
  lines: [
    { kind: "child", student_id: "alex", label: "Alex Demo", detail: "Junior Beginners · November", amount_cents: 8000 },
    { kind: "child", student_id: "sam", label: "Sam Demo", detail: "Junior Beginners · November", amount_cents: 8000 },
    { kind: "discount", label: "Sibling discount", amount_cents: -2000 },
  ],
  periods: [],
  last_payment: { amount_cents: 6000, paid_on: "2026-10-03", method_label: "Paid in cash" },
};

function render(summary: ParentMoneySummary, extra: Partial<Parameters<typeof MoneySummaryCard>[0]> = {}) {
  return renderToStaticMarkup(
    <MoneySummaryCard summary={summary} todayIso="2026-11-20" hasInvoices onPay={() => {}} payPending={false} paySettling={false} {...extra} />,
  );
}

describe("MoneySummaryCard", () => {
  it("shows the backend figure, date, each child and the discount as its own line", () => {
    const html = render(due);
    expect(html).toContain("$140.00");
    expect(html).toContain("Due Tue, Dec 1");
    expect(html).toContain("Alex Demo");
    expect(html).toContain("Sam Demo");
    expect(html).toContain("Sibling discount");
    expect(html).toContain("−$20.00");
    expect(html).toContain('aria-label="minus $20.00"');
    expect(html).toContain("Total for your family");
    expect(html).toContain("Pay $140.00");
    expect(html).not.toContain("Balance due");
  });

  it("says nothing to pay and the last payment in words", () => {
    const html = render({ ...due, amount_due_cents: 0, due_date: null, lines: [] });
    expect(html).toContain("$0.00");
    expect(html).toContain("Nothing to pay right now.");
    expect(html).toContain("Last payment: $60.00 on Oct 3, paid in cash.");
    expect(html).not.toContain("Pay $");
  });

  it("offers how to pay instead of a Pay button when the academy is desk-paid", () => {
    const html = render({ ...due, can_pay_online: false }, { paymentInstructions: "Cash or check at the desk." });
    expect(html).toContain("How to pay");
    expect(html).toContain("Cash or check at the desk.");
    expect(html).not.toContain('data-testid="pay-balance"');
  });
});
