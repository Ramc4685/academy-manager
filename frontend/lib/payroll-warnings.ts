import type { AdminMonthlyPayrollRow } from "./api/v2/payroll";
import type { PayoutWarning, PayoutWarningReason } from "./api/v2/payouts";

const WARNING_LABELS: Record<PayoutWarningReason, string> = {
  missing_session_price_for_percent_revenue:
    "Missing session price for percent-of-revenue pay",
  missing_rate: "Missing coach pay rate",
  missing_percent: "Missing percent on coach pay rate",
};

const REPAIR_ACTIONS: Record<string, string> = {
  set_session_fee_and_recompute: "Set session fee, then recompute payout.",
  set_coach_rate_and_recompute: "Set coach rate, then recompute payout.",
};

export function rowHasUnresolvedWarnings(row: AdminMonthlyPayrollRow): boolean {
  return row.warning_status === "unresolved" && row.warning_count > 0;
}

export function payoutWarningLabel(warning: Pick<PayoutWarning, "reason" | "message">): string {
  return WARNING_LABELS[warning.reason] ?? warning.message;
}

export function payoutWarningRepairAction(
  warning: Pick<PayoutWarning, "repair_action">,
): string {
  return REPAIR_ACTIONS[warning.repair_action] ?? warning.repair_action;
}

export function approvalWarningMessage(warningCount: number): string | null {
  if (warningCount <= 0) return null;
  const noun = warningCount === 1 ? "warning" : "warnings";
  return `Resolve ${warningCount} payout ${noun} before approving or marking this payout paid.`;
}
