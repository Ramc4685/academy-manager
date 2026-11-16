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
  unresolved_unpaid_count: number;
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

/** How a percent coach's invoiced-tuition base is counted (owner only, audited). */
export interface PayrollSettings {
  payroll_ach_discount_reduces_base: boolean;
  payroll_count_checkout_first_month: boolean;
  payroll_cancelled_class_share: "ran_only" | "all_scheduled";
  payroll_missing_invoices: "block" | "pay_zero";
  /** First month (YYYY-MM) assistant coaches are paid in the app; null = never. */
  payroll_assistant_pay_from: string | null;
}

export async function getPayrollSettings(): Promise<PayrollSettings> {
  return apiFetch<PayrollSettings>("/admin/payroll-settings", { method: "GET" });
}

export async function updatePayrollSettings(settings: PayrollSettings): Promise<PayrollSettings> {
  return apiFetch<PayrollSettings>("/admin/payroll-settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}
