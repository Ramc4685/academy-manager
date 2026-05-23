/**
 * v2 students client.
 *
 * Wraps the admin student detail/edit endpoints.
 */
import { apiFetch } from "../client";
import { type AdminStudentView } from "../admin";

export interface AdminStudentDetail extends AdminStudentView {
  date_of_birth?: string | null;
  level?: string | null;
  notes?: string | null;
  parent_phone?: string | null;
  parent_details?: string | null;
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
