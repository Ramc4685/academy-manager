import { describe, expect, it } from "vitest";

import {
  payrollRowNeedsWarning,
  rateTimelineIssueLabel,
  unpaidReasonGuidance,
  unpaidReasonLabel,
} from "./payroll-warnings";

describe("payroll warning presentation helpers", () => {
  it("flags partial unpaid payroll even when the coach total is non-zero", () => {
    expect(
      payrollRowNeedsWarning({
        session_count: 4,
        total_amount_cents: 15000,
        unresolved_unpaid_count: 1,
      }),
    ).toBe(true);
  });

  it("keeps the old zero-total no-rate warning path", () => {
    expect(
      payrollRowNeedsWarning({
        session_count: 2,
        total_amount_cents: 0,
        unresolved_unpaid_count: 0,
      }),
    ).toBe(true);
  });

  it("labels structured unpaid reasons with admin-actionable guidance", () => {
    expect(unpaidReasonLabel("rate_gap")).toBe("Rate gap");
    expect(unpaidReasonGuidance("rate_gap")).toContain("Repair the coach pay-rate window");
    expect(unpaidReasonLabel("missing_session_price_for_percent_revenue")).toBe(
      "Missing session price",
    );
  });

  it("labels timeline diagnostics", () => {
    expect(rateTimelineIssueLabel("duplicate_active_rows")).toBe("Duplicate active rates");
    expect(rateTimelineIssueLabel("overlap")).toBe("Overlapping rate windows");
  });
});
