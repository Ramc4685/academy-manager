/**
 * v2 payouts client.
 *
 * - Payout periods — the persisted, line-level record behind a payout.
 *   `generatePayoutPeriod` is idempotent on (coach, window): opening a
 *   payout review materialises the draft period if it does not exist
 *   yet and returns the existing one otherwise.
 * - Admin corrections — recompute, reopen (with reason), per-line
 *   override (with reason), and the audit trail behind all of them.
 *
 * No SaaS page should call `/api/*` legacy routes.
 */
import { apiFetch, apiFetchBlob } from "../client";
export type PayoutPeriodStatus = "draft" | "approved" | "paid";
export type PayoutWarningReason =
  | "missing_session_price_for_percent_revenue"
  | "missing_invoiced_tuition_for_percent_revenue"
  | "percent_rate_on_assistant"
  | "missing_rate"
  | "missing_percent"
  | "unattributed_manual_invoices";
export type PayoutWarningSeverity = "blocking" | "warning";

export interface PayoutWarning {
  occurrence_id: string;
  reason: PayoutWarningReason;
  severity: PayoutWarningSeverity;
  message: string;
  occurred_at: string | null;
  session_id: string | null;
  session_title: string | null;
  coach_id: string;
  repair_action: string;
}

export interface AdminPayoutPeriodLineView {
  occurrence_id: string;
  coach_id: string;
  basis: "scheduled" | "substitute" | "actual" | "assistant";
  minutes: string;
  amount_cents: number;
  currency: string;
  rate_id: string;
  percent_bps: number | null;
  expected_revenue_cents: number | null;
  original_amount_cents: number | null;
  adjustment_reason: string | null;
  occurred_at: string | null;
  session_title: string | null;
}

export interface AdminUnpaidOccurrenceView {
  occurrence_id: string;
  occurred_at: string | null;
  session_id: string | null;
  session_title: string | null;
  reason:
    | "no_rate_configured"
    | "rate_gap"
    | "missing_session_price_for_percent_revenue"
    | "attendance_override"
    | "replaced_by_actual_coach"
    | "unknown_unpaid_reason"
    | PayoutWarningReason;
  detail: string | null;
  unresolved: boolean;
  severity: PayoutWarningSeverity | null;
  message: string | null;
  coach_id: string | null;
  repair_action: string | null;
  /** For `replaced_by_actual_coach`, the coach paid instead of this one. */
  attributed_coach_id: string | null;
}

export interface AdminPayoutPeriodView {
  period_id: string;
  /** Bumped by every write; sent back as `expected_version` so a stale screen gets a 409. */
  version: number;
  coach_id: string;
  period_start: string;
  period_end: string;
  status: PayoutPeriodStatus;
  currency: string;
  total_amount_cents: number;
  lines: AdminPayoutPeriodLineView[];
  unpaid_occurrence_ids: string[];
  unpaid_occurrences: AdminUnpaidOccurrenceView[];
  payout_warnings: PayoutWarning[];
  generated_at: string;
  approved_at: string | null;
  paid_at: string | null;
  paid_method: string | null;
  paid_amount_cents: number | null;
  paid_reference: string | null;
  /** "expected" = a legacy draft priced on expected revenue: recompute before approving. */
  revenue_basis: "expected" | "invoiced";
  /** True when the recorded paid amount is not the period total. */
  paid_amount_differs: boolean;
}

export type PayoutAuditAction =
  | "generated"
  | "recomputed"
  | "reopened"
  | "approved"
  | "marked_paid"
  | "line_overridden"
  | "line_override_cleared";

export interface PayoutAuditEntryView {
  audit_id: string;
  period_id: string;
  occurrence_id: string | null;
  action: PayoutAuditAction;
  actor_id: string;
  at: string;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface PayoutAuditTrailView {
  entries: PayoutAuditEntryView[];
}

/** Idempotent: returns the existing period for the window if one exists. */
export async function generatePayoutPeriod(input: {
  coach_id: string;
  period_start: string;
  period_end: string;
}): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>("/admin/payout-periods/generate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getPayoutPeriod(periodId: string): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}`,
    { method: "GET" },
  );
}

export const PAYOUT_CONFLICT_MESSAGE = "Someone else changed this payout — reload to see it.";

/** The message a failed payout write shows; a lost race gets the reload prompt. */
export function payoutErrorMessage(err: Error): string {
  return (err as { code?: string }).code === "Finance.PayoutPeriodConflict"
    ? PAYOUT_CONFLICT_MESSAGE
    : err.message;
}

/** `expectedVersion` is the version on screen; a stale one is a 409. */
export async function recomputePayoutPeriod(
  periodId: string,
  expectedVersion: number,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/recompute`,
    { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) },
  );
}

export async function reopenPayoutPeriod(
  periodId: string,
  reason: string,
  expectedVersion: number,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/reopen`,
    { method: "POST", body: JSON.stringify({ reason, expected_version: expectedVersion }) },
  );
}

export async function approvePayoutPeriod(
  periodId: string,
  expectedVersion: number,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/approve`,
    { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) },
  );
}

/** Pass `amount_cents: null` to clear an existing override. */
export async function overridePayoutLine(
  periodId: string,
  occurrenceId: string,
  input: { amount_cents: number | null; reason: string; expected_version: number },
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/lines/${encodeURIComponent(occurrenceId)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

/** Download the period as an Excel workbook and hand back the Blob. */
export async function exportPayoutPeriodXlsx(periodId: string): Promise<Blob> {
  return apiFetchBlob(`/admin/payout-periods/${encodeURIComponent(periodId)}/export`, {
    method: "GET",
  });
}

export async function getPayoutAuditTrail(periodId: string): Promise<PayoutAuditTrailView> {
  return apiFetch<PayoutAuditTrailView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/audit`,
    { method: "GET" },
  );
}

export interface MarkPayoutPaidInput {
  method: "bank_transfer" | "cash" | "check" | "other";
  paid_at: string;
  amount_cents: number;
  reference?: string | null;
  expected_version: number;
}

export async function markPayoutPeriodPaid(
  periodId: string,
  input: MarkPayoutPaidInput,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/mark-paid`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

/** The mark-paid body from the dialog's fields and the version it opened on. */
export function markPaidInput(fields: {
  method: MarkPayoutPaidInput["method"];
  paidAt: string;
  amount: string;
  reference: string;
  versionAtOpen: number;
}): MarkPayoutPaidInput {
  return {
    method: fields.method,
    paid_at: new Date(fields.paidAt).toISOString(),
    amount_cents: Math.round(parseFloat(fields.amount) * 100),
    reference: fields.reference || null,
    expected_version: fields.versionAtOpen,
  };
}
