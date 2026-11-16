import type { AdminMonthlyPayrollRow } from "./api/v2/payroll";
import type { PayoutWarning, PayoutWarningReason } from "./api/v2/payouts";

export type UnpaidOccurrenceReason =
  | "no_rate_configured"
  | "rate_gap"
  | "missing_session_price_for_percent_revenue"
  | "attendance_override"
  | "replaced_by_actual_coach"
  | "unknown_unpaid_reason"
  | "missing_invoiced_tuition_for_percent_revenue"
  | "percent_rate_on_assistant"
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
  missing_invoiced_tuition_for_percent_revenue: "No invoiced tuition for this class and month",
  percent_rate_on_assistant: "Percent rate on an assistant",
  missing_rate: "Missing coach pay rate",
  missing_percent: "Missing percent on coach pay rate",
  unattributed_manual_invoices: "Invoices with no class",
};

const REPAIR_ACTIONS: Record<string, string> = {
  set_session_fee_and_recompute: "Set session fee, then recompute payout.",
  set_coach_rate_and_recompute: "Set coach rate, then recompute payout.",
  invoice_class_month_and_recompute: "Invoice the class for the month, then recompute payout.",
  override_assistant_pay_and_recompute:
    "Set an attendance pay override for this class, or give the coach a per-session or per-hour rate, then recompute payout.",
  attach_invoice_to_enrollment_and_recompute:
    "Check those invoices: tuition on an invoice with no enrollment is in no coach's base.",
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
    case "missing_invoiced_tuition_for_percent_revenue":
      return "No invoiced tuition";
    case "percent_rate_on_assistant":
      return "Percent rate on assistant";
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
    case "missing_invoiced_tuition_for_percent_revenue":
      return "Invoice the class for this month (or let the academy pay $0 for uninvoiced months), then recompute.";
    case "percent_rate_on_assistant":
      return "Give the assistant a per-session or per-hour rate (or an override on the attendance), then recompute.";
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

export type ApprovalBlock = { kind: "preview" | "recompute"; message: string } | null;

/**
 * Why a draft payout cannot be approved yet, from the period itself (L7).
 * Mirrors the backend rule: approve only after the month has ended, from a
 * calculation made after that, on the invoiced-tuition basis.
 */
export function approvalBlock(
  period: { status: string; period_end: string; generated_at: string; revenue_basis: string },
  now: Date,
  monthEndLabel: string,
): ApprovalBlock {
  if (period.status !== "draft") return null;
  const end = new Date(period.period_end).getTime();
  if (now.getTime() < end) {
    return { kind: "preview", message: `Preview. Approve unlocks after ${monthEndLabel}.` };
  }
  if (period.revenue_basis !== "invoiced") {
    return {
      kind: "recompute",
      message:
        "This draft was calculated on expected revenue. Recompute it on invoiced tuition before approving.",
    };
  }
  if (new Date(period.generated_at).getTime() < end) {
    return {
      kind: "recompute",
      message: "This draft was calculated before the month ended. Recompute it before approving.",
    };
  }
  return null;
}

/** The percent column's basis label: what the percentage was taken of. */
export function percentBasisLabel(revenueBasis: string): string {
  return revenueBasis === "invoiced" ? "% of invoiced tuition" : "(legacy: expected revenue)";
}
