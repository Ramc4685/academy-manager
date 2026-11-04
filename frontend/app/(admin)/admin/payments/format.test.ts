import { describe, expect, it } from "vitest";

import type { AdminPaymentView } from "@/lib/api/admin";

import {
  formatPeriodLabel,
  paymentDisplayLabel,
  paymentRowTitle,
  reconciliationLabel,
  reconciliationStatusLabel,
  skipReasonLabel,
} from "./format";

/**
 * Issue #892 — the money screens spoke Stripe, not academy.
 *
 * Periods read as keys ("2026-09"), skipped billing deferrals read as
 * database codes ("skipped by admin"). Both are what an admin sees while
 * deciding whether to refund or re-run a month, so both are wording, not
 * formatting trivia.
 */
describe("formatPeriodLabel (#892)", () => {
  it("renders a YYYY-MM period as a month and year", () => {
    expect(formatPeriodLabel("2026-09")).toBe("September 2026");
    expect(formatPeriodLabel("2026-01")).toBe("January 2026");
    expect(formatPeriodLabel("2025-12")).toBe("December 2025");
  });

  it("is timezone-proof: the first of the month never slips to the month before", () => {
    // A naive `new Date("2026-09")` is parsed as UTC midnight and then
    // rendered in local time, which reads as August in the Americas.
    expect(formatPeriodLabel("2026-09")).not.toContain("August");
  });

  it("returns null for a missing period so callers keep their own fallback", () => {
    expect(formatPeriodLabel(null)).toBeNull();
    expect(formatPeriodLabel(undefined)).toBeNull();
    expect(formatPeriodLabel("")).toBeNull();
  });

  it("hands back anything that is not a period key rather than dropping it", () => {
    expect(formatPeriodLabel("2026")).toBe("2026");
    expect(formatPeriodLabel("2026-13")).toBe("2026-13");
    expect(formatPeriodLabel("winter term")).toBe("winter term");
  });

  it("is used by the invoice label, so no row says 'Tuition for 2026-09'", () => {
    const payment = { period: "2026-09", stripe_linked: false } as AdminPaymentView;
    expect(paymentDisplayLabel(payment)).toBe("Tuition for September 2026");
  });
});

describe("skipReasonLabel (#892)", () => {
  it("reads the known codes as sentences, not as keys", () => {
    expect(skipReasonLabel("skipped_by_admin")).toBe("Skipped this month");
    expect(skipReasonLabel("legacy_skip_period")).toBe("Skipped this month");
    expect(skipReasonLabel("enrollment_paused")).toBe("Enrollment paused");
    expect(skipReasonLabel("pending_cancellation")).toBe("Leaving at the end of the period");
    expect(skipReasonLabel("fixed_pause")).toBe("Paused until a set date");
  });

  it("sentence-cases an unknown code instead of printing snake_case", () => {
    // The backend can stamp a new deferral type without the UI shipping again.
    expect(skipReasonLabel("some_future_reason")).toBe("Some future reason");
    expect(skipReasonLabel("")).toBe("");
  });
});

/**
 * UI-5 — the All invoices rows printed internal strings ("Stripe linked, app
 * ledger pending", "orphan charge", "stripe synced") and repeated the month in
 * every row title although the Period column already shows it.
 */
describe("reconciliationLabel (UI-5)", () => {
  const row = (overrides: Partial<AdminPaymentView>) =>
    ({ status: "paid", stripe_linked: true, reconciliation_status: null, ...overrides }) as AdminPaymentView;

  it("says nothing on a healthy Stripe row", () => {
    expect(reconciliationLabel(row({ reconciliation_status: "stripe_synced" }))).toBeNull();
    expect(reconciliationLabel(row({ status: "paid" }))).toBeNull();
    expect(reconciliationLabel(row({ status: "pending", stripe_linked: false }))).toBeNull();
  });

  it("replaces 'Stripe linked, app ledger pending' with plain words", () => {
    const pending = reconciliationLabel(row({ status: "pending" }));
    expect(pending).toBe("Waiting for Stripe to confirm this payment");
    expect(reconciliationLabel(row({ reconciliation_status: "stripe_linked_pending" }))).toBe(pending);
    expect(reconciliationLabel(row({ status: "partially_paid" }))).toBe(pending);
  });

  it("points the rows that need a person at Billing Health", () => {
    expect(reconciliationStatusLabel("missing_allocation")).toBe(
      "Payment received but not matched to this invoice. Check Billing Health.",
    );
    expect(reconciliationStatusLabel("orphan_charge")).toContain("Check Billing Health");
  });

  it("reads failed attempts and decline codes as sentences", () => {
    expect(reconciliationStatusLabel("payment_failed")).toBe("The last payment attempt failed");
    expect(reconciliationStatusLabel("card_declined")).toBe(
      "The last payment attempt failed: card declined",
    );
  });

  it("never prints a raw code, even for one it does not know", () => {
    for (const code of ["stripe_linked_pending", "missing_allocation", "orphan_charge", "some_new_code"]) {
      const label = reconciliationStatusLabel(code) ?? "";
      expect(label).not.toContain("_");
      expect(label).not.toMatch(/ledger/i);
    }
    expect(reconciliationStatusLabel("some_new_code")).toBe("Some new code");
  });
});

describe("paymentRowTitle (UI-5)", () => {
  it("does not repeat the month the Period column already shows", () => {
    const payment = { period: "2026-09", stripe_linked: false } as AdminPaymentView;
    expect(paymentRowTitle(payment)).toBe("Monthly tuition");
    // Dialogs still name the month: there it is the only context.
    expect(paymentDisplayLabel(payment)).toBe("Tuition for September 2026");
  });

  it("falls back to the payment kind when there is no period", () => {
    expect(paymentRowTitle({ period: null, stripe_linked: true } as AdminPaymentView)).toBe("Stripe payment");
    expect(paymentRowTitle({ period: null, stripe_linked: false } as AdminPaymentView)).toBe("Manual payment");
  });
});
