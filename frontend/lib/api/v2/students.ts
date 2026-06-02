/**
 * v2 students client.
 *
 * Wraps the admin student detail/edit endpoints.
 */
import { apiFetch } from "../client";
import { type AdminStudentView } from "../admin";

export interface AdminStudentSessionSummary {
  enrollment_id: string;
  session_id: string;
  session_title: string;
  location?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  status: string;
  payment_mode?: string | null;
  subscription_status?: string | null;
  amount_cents?: number | null;
}

export interface AdminStudentPaymentSummary {
  payment_id: string;
  session_id?: string | null;
  period?: string | null;
  amount_cents: number;
  paid_amount_cents: number;
  balance_due_cents: number;
  status: string;
  payment_method?: string | null;
  created_at: string;
}

export interface AdminStudentCurrentPaymentSummary {
  amount_cents: number;
  source: "invoice" | "session_price";
  status: string;
  period?: string | null;
  payment_id?: string | null;
  session_id?: string | null;
}

export interface AdminStudentDetail extends AdminStudentView {
  date_of_birth?: string | null;
  level?: string | null;
  notes?: string | null;
  parent_phone?: string | null;
  parent_details?: string | null;
  enrolled_sessions: AdminStudentSessionSummary[];
  payment_history: AdminStudentPaymentSummary[];
  current_payment?: AdminStudentCurrentPaymentSummary | null;
}

export async function getAdminStudent(studentId: string): Promise<AdminStudentDetail | null> {
  return apiFetch<AdminStudentDetail>(`/admin/students/${encodeURIComponent(studentId)}`, {
    method: "GET",
  });
}

export interface UpdateAdminStudentRequest {
  full_name?: string;
  date_of_birth?: string | null;
  level?: string | null;
  status?: "active" | "paused" | "inactive";
  parent_id?: string;
  notes?: string | null;
  reason?: string;
}

export function updateAdminStudent(
  studentId: string,
  payload: UpdateAdminStudentRequest,
): Promise<AdminStudentDetail> {
  return apiFetch<AdminStudentDetail>(`/admin/students/${encodeURIComponent(studentId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export interface TransferEnrollmentRequest {
  target_session_id: string;
  effective_date: string; // ISO date YYYY-MM-DD
  reason?: string | null;
}

export function transferEnrollment(
  enrollmentId: string,
  payload: TransferEnrollmentRequest,
): Promise<unknown> {
  return apiFetch(`/admin/enrollments/${encodeURIComponent(enrollmentId)}/transfer`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
