import { describe, expect, it } from "vitest";
import {
  approvalBlock,
  approvalWarningMessage,
  percentBasisLabel,
  payrollRowNeedsWarning,
  payoutWarningLabel,
  payoutWarningRepairAction,
  rateTimelineIssueLabel,
  rowHasUnresolvedWarnings,
  unpaidReasonGuidance,
  unpaidReasonLabel,
} from "./payroll-warnings";
import type { AdminMonthlyPayrollRow } from "./api/v2/payroll";
import type { PayoutWarning } from "./api/v2/payouts";

describe("payroll warning presentation", () => {
  it("uses backend warning count instead of inferring from zero totals", () => {
    const explicitFreeSession: AdminMonthlyPayrollRow = {
      coach_id: "coach-free",
      coach_name: "Free Coach",
      session_count: 3,
      total_amount_cents: 0,
      currency: "USD",
      status: "draft",
      period_id: "pp-free",
      unresolved_unpaid_count: 0,
      warning_count: 0,
      warning_status: "clear",
    };

    expect(rowHasUnresolvedWarnings(explicitFreeSession)).toBe(false);
  });

  it("shows reason-specific copy and repair action for missing session price", () => {
    const warning: PayoutWarning = {
      occurrence_id: "occ-1",
      reason: "missing_session_price_for_percent_revenue",
      severity: "blocking",
      message: "Missing session price for percent-of-revenue pay.",
      occurred_at: "2026-06-10T18:00:00Z",
      session_id: "sess-1",
      session_title: "Junior Squad",
      coach_id: "coach-1",
      repair_action: "set_session_fee_and_recompute",
    };

    expect(payoutWarningLabel(warning)).toContain("Missing session price");
    expect(payoutWarningRepairAction(warning)).toContain("Set session fee");
  });

  it("blocks approval and mark-paid copy when unresolved warnings exist", () => {
    expect(approvalWarningMessage(2)).toBe(
      "Resolve 2 payout warnings before approving or marking this payout paid.",
    );
  });

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

describe("replaced-by-substitute reason (#228)", () => {
  it("labels a displaced scheduled coach's occurrence as replaced", () => {
    expect(unpaidReasonLabel("replaced_by_actual_coach")).toBe("Replaced");
  });

  it("guides the admin to check the attribution rather than a rate repair", () => {
    expect(unpaidReasonGuidance("replaced_by_actual_coach")).toContain("replacement coach");
  });
});

describe("approval gate (L7)", () => {
  const draft = {
    status: "draft",
    period_end: "2026-11-01T05:00:00Z",
    generated_at: "2026-11-02T00:00:00Z",
    revenue_basis: "invoiced",
  };
  const afterMonth = new Date("2026-11-03T00:00:00Z");

  it("shows a preview banner while the month is still running", () => {
    expect(approvalBlock(draft, new Date("2026-10-20T00:00:00Z"), "Oct 31")).toEqual({
      kind: "preview",
      message: "Preview. Approve unlocks after Oct 31.",
    });
  });

  it("asks for a recompute on a legacy or stale draft", () => {
    expect(approvalBlock({ ...draft, revenue_basis: "expected" }, afterMonth, "Oct 31")?.kind).toBe(
      "recompute",
    );
    expect(
      approvalBlock({ ...draft, generated_at: "2026-10-25T00:00:00Z" }, afterMonth, "Oct 31")?.kind,
    ).toBe("recompute");
  });

  it("allows a post-month invoiced draft and never blocks a locked period", () => {
    expect(approvalBlock(draft, afterMonth, "Oct 31")).toBeNull();
    expect(approvalBlock({ ...draft, status: "approved" }, new Date(0), "Oct 31")).toBeNull();
  });

  it("labels the percent basis", () => {
    expect(percentBasisLabel("invoiced")).toBe("% of invoiced tuition");
    expect(percentBasisLabel("expected")).toBe("(legacy: expected revenue)");
  });

  it("names the new blocking warnings", () => {
    expect(
      payoutWarningLabel({ reason: "missing_invoiced_tuition_for_percent_revenue", message: "" }),
    ).toBe("No invoiced tuition for this class and month");
    expect(payoutWarningRepairAction({ repair_action: "invoice_class_month_and_recompute" })).toBe(
      "Invoice the class for the month, then recompute payout.",
    );
    expect(unpaidReasonLabel("percent_rate_on_assistant")).toBe("Percent rate on assistant");
  });
});
