/**
 * v2 payouts client.
 *
 * - `listAdminPayouts()` — calls the v2 BFF `/admin/finance/payouts`
 *   (rolled-up rows for the payouts list page).
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
import { listPayouts } from "../admin";

export type { AdminPayoutView } from "../admin";

/**
 * @deprecated Use `listMonthlyPayroll()` from `v2/payroll.ts` instead.
 * Calls the legacy derived-list route which will be removed after
 * feat/coach-payroll-month-first ships.
 */
export async function listAdminPayouts() {
  return listPayouts();
}

export type PayoutPeriodStatus = "draft" | "approved" | "paid";

export interface AdminPayoutPeriodLineView {
  occurrence_id: string;
  coach_id: string;
  basis: "scheduled" | "substitute" | "actual";
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
  session_title: string | null;
}

export interface AdminPayoutPeriodView {
  period_id: string;
  coach_id: string;
  period_start: string;
  period_end: string;
  status: PayoutPeriodStatus;
  currency: string;
  total_amount_cents: number;
  lines: AdminPayoutPeriodLineView[];
  unpaid_occurrence_ids: string[];
  unpaid_occurrences: AdminUnpaidOccurrenceView[];
  generated_at: string;
  approved_at: string | null;
  paid_at: string | null;
  paid_method: string | null;
  paid_amount_cents: number | null;
  paid_reference: string | null;
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

export async function recomputePayoutPeriod(periodId: string): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/recompute`,
    { method: "POST" },
  );
}

export async function reopenPayoutPeriod(
  periodId: string,
  reason: string,
): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/reopen`,
    { method: "POST", body: JSON.stringify({ reason }) },
  );
}

export async function approvePayoutPeriod(periodId: string): Promise<AdminPayoutPeriodView> {
  return apiFetch<AdminPayoutPeriodView>(
    `/admin/payout-periods/${encodeURIComponent(periodId)}/approve`,
    { method: "POST" },
  );
}

/** Pass `amount_cents: null` to clear an existing override. */
export async function overridePayoutLine(
  periodId: string,
  occurrenceId: string,
  input: { amount_cents: number | null; reason: string },
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
