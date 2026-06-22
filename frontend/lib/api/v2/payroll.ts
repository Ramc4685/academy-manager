import { apiFetch, apiFetchBlob } from "../client";

export type MonthlyPayrollStatus = "not_generated" | "draft" | "approved" | "paid";

export interface AdminMonthlyPayrollRow {
  coach_id: string;
  coach_name: string | null;
  session_count: number;
  total_amount_cents: number;
  currency: string;
  status: MonthlyPayrollStatus;
  period_id: string | null;
  warning_count: number;
  warning_status: "clear" | "unresolved";
}

export interface AdminMonthlyPayrollView {
  month: string;
  period_start: string;
  period_end: string;
  rows: AdminMonthlyPayrollRow[];
  total_amount_cents: number;
}

export interface BulkPayrollResult {
  month: string;
  generated: number;
  skipped: number;
  recomputed: number;
}

export async function listMonthlyPayroll(month: string): Promise<AdminMonthlyPayrollView> {
  return apiFetch<AdminMonthlyPayrollView>(
    `/admin/payroll/${encodeURIComponent(month)}`, { method: "GET" });
}

export async function generateMonthlyPayroll(month: string): Promise<BulkPayrollResult> {
  return apiFetch<BulkPayrollResult>(
    `/admin/payroll/${encodeURIComponent(month)}/generate`, { method: "POST" });
}

export async function recomputeMonthlyPayroll(month: string): Promise<BulkPayrollResult> {
  return apiFetch<BulkPayrollResult>(
    `/admin/payroll/${encodeURIComponent(month)}/recompute`, { method: "POST" });
}

export async function exportMonthlyPayrollXlsx(month: string): Promise<Blob> {
  return apiFetchBlob(
    `/admin/payroll/${encodeURIComponent(month)}/export`, { method: "GET" });
}
