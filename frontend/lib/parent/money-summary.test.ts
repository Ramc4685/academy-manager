import { describe, expect, it } from "vitest";

import type { ParentMoneySummary } from "@/lib/api/parent";
import { creditCopy, dueLine, paymentStatusWord, showFamilyTotal } from "./money-summary";

const base: ParentMoneySummary = {
  currency: "usd",
  amount_due_cents: 14000,
  due_date: "2026-12-01",
  overdue: false,
  days_overdue: 0,
  multiple_due_dates: false,
  can_pay_online: true,
  lines: [{ kind: "child", label: "Sam Demo", amount_cents: 14000 }],
  periods: [],
  last_payment: null,
};

describe("money summary wording", () => {
  it("says when it is due, today, or how late", () => {
    expect(dueLine(base, "2026-11-20")).toBe("Due Tue, Dec 1");
    expect(dueLine(base, "2026-12-01")).toBe("Due today");
    expect(dueLine({ ...base, multiple_due_dates: true }, "2026-11-20")).toBe("First payment due Tue, Dec 1");
    expect(
      dueLine({ ...base, due_date: "2026-11-01", overdue: true, days_overdue: 25 }, "2026-11-26"),
    ).toBe("Was due Sun, Nov 1 · 25 days ago");
    expect(dueLine({ ...base, amount_due_cents: 0, due_date: null }, "2026-11-26")).toBeNull();
  });

  it("shows a family total only when there is more than one plain line", () => {
    expect(showFamilyTotal(base)).toBe(false);
    expect(
      showFamilyTotal({
        ...base,
        lines: [...base.lines, { kind: "discount", label: "Sibling discount", amount_cents: -2000 }],
      }),
    ).toBe(true);
  });

  it("never shows a raw payment status", () => {
    expect(paymentStatusWord("succeeded")).toBe("Paid");
    expect(paymentStatusWord("failed")).toBe("Did not go through");
    expect(paymentStatusWord("partially_refunded")).toBe("Partly refunded");
    expect(creditCopy(2000)).toBe("$20.00 credit on your account. It comes off your next invoice.");
  });
});

describe("Payments page money source", () => {
  it("never sums invoice balances in the browser", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const page = readFileSync(resolve(__dirname, "../../app/(parent)/parent/payments/page.tsx"), "utf8");
    expect(page).not.toMatch(/reduce\([\s\S]{0,80}balance_due_cents/);
    expect(page).not.toMatch(/currentBalance/);
    expect(page).not.toContain("Balance due");
    expect(page).toContain("getParentMoneySummary");
    expect(page).not.toContain("payments-next-class-link");
  });
});
