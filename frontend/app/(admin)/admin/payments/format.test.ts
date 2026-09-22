import { describe, expect, it } from "vitest";

import type { AdminPaymentView } from "@/lib/api/admin";

import { formatPeriodLabel, paymentDisplayLabel, skipReasonLabel } from "./format";

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
