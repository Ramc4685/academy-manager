import type { AdminMonthlyPayrollRow } from "./api/v2/payroll";
import type { PayoutWarning, PayoutWarningReason } from "./api/v2/payouts";

export type UnpaidOccurrenceReason =
  | "no_rate_configured"
  | "rate_gap"
  | "missing_session_price_for_percent_revenue"
  | "attendance_override"
  | "replaced_by_actual_coach"
  | "unknown_unpaid_reason"
  | "missing_rate"
  | "missing_percent";

export type RateTimelineIssueType =
  | "gap"
  | "overlap"
  | "duplicate_effective_from"
  | "duplicate_active_rows"
  | "multiple_open_ended_rows"
  | "invalid_window"
  | "malformed_history";

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

export function payrollRowNeedsWarning(row: {
  session_count: number;
  total_amount_cents: number;
  unresolved_unpaid_count?: number;
}): boolean {
  return (
    row.session_count > 0 &&
    ((row.unresolved_unpaid_count ?? 0) > 0 || row.total_amount_cents === 0)
  );
}

export function unpaidReasonLabel(reason: UnpaidOccurrenceReason | string): string {
  switch (reason) {
    case "no_rate_configured":
      return "No rate configured";
    case "rate_gap":
      return "Rate gap";
    case "missing_session_price_for_percent_revenue":
      return "Missing session price";
    case "missing_rate":
      return "Missing coach pay rate";
    case "missing_percent":
      return "Missing percent";
    case "attendance_override":
      return "Attendance override";
    case "replaced_by_actual_coach":
      return "Replaced";
    default:
      return "Needs review";
  }
}

export function unpaidReasonGuidance(reason: UnpaidOccurrenceReason | string): string {
  switch (reason) {
    case "no_rate_configured":
      return "Set a coach pay rate, then recompute the draft payout period.";
    case "rate_gap":
      return "Repair the coach pay-rate window, then recompute the draft payout period.";
    case "missing_session_price_for_percent_revenue":
      return "Add the missing session price basis, then recompute this draft payout period.";
    case "missing_rate":
      return "Set a coach pay rate, then recompute this draft payout period.";
    case "missing_percent":
      return "Set the percent on the coach pay rate, then recompute this draft payout period.";
    case "attendance_override":
      return "Review the attendance entry that explains why this occurrence was not paid.";
    case "replaced_by_actual_coach":
      return "A replacement coach was paid for this session. Check the attribution if that is wrong.";
    default:
      return "Review the occurrence details before approving payroll.";
  }
}

export function rateTimelineIssueLabel(issueType: RateTimelineIssueType | string): string {
  switch (issueType) {
    case "gap":
      return "Rate gap";
    case "overlap":
      return "Overlapping rate windows";
    case "duplicate_effective_from":
      return "Duplicate effective start";
    case "duplicate_active_rows":
      return "Duplicate active rates";
    case "multiple_open_ended_rows":
      return "Multiple open-ended rates";
    case "invalid_window":
      return "Invalid rate window";
    case "malformed_history":
      return "Malformed rate history";
    default:
      return "Timeline warning";
  }
}
