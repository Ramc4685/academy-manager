import { describe, expect, it } from "vitest";
import {
  approvalWarningMessage,
  payoutWarningLabel,
  payoutWarningRepairAction,
  rowHasUnresolvedWarnings,
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
});
