export type UnpaidOccurrenceReason =
  | "no_rate_configured"
  | "rate_gap"
  | "missing_session_price_for_percent_revenue"
  | "attendance_override"
  | "unknown_unpaid_reason";

export type RateTimelineIssueType =
  | "gap"
  | "overlap"
  | "duplicate_effective_from"
  | "duplicate_active_rows"
  | "multiple_open_ended_rows"
  | "invalid_window"
  | "malformed_history";

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
    case "attendance_override":
      return "Attendance override";
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
    case "attendance_override":
      return "Review the attendance entry that explains why this occurrence was not paid.";
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
