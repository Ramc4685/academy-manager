/**
 * v2 students client.
 *
 * Wraps the admin students endpoints. The list endpoint is shipped on
 * the BFF today (`GET /api/v2/admin/students`). A single-student detail
 * endpoint and a profile-update endpoint are NOT yet exposed by the
 * BFF, so the helpers below either narrow the list to a single id or
 * surface a clear error pointing at the missing route. Replace those
 * implementations once the routes land.
 */
import { apiFetch } from "../client";
import { listAdminStudents, type AdminStudentView } from "../admin";

export interface AdminStudentDetail extends AdminStudentView {
  // Reserved for forthcoming fields (notes, waiver_status, billing_summary,
  // emergency contacts). Keep the type open so the detail page can grow.
  notes?: string | null;
}

/**
 * Fetch a single student by id.
 *
 * Today this is implemented by scanning the paginated admin students
 * list (the BFF does not yet expose `GET /admin/students/{id}`). For
 * academies with thousands of students this is acceptable as a Wave 5
 * placeholder; the call sites do not assume O(1) lookup.
 *
 * TODO(wave5-A): switch to `apiFetch<AdminStudentDetail>(...)` once the
 * detail route ships.
 */
export async function getAdminStudent(studentId: string): Promise<AdminStudentDetail | null> {
  // Scan up to a few pages. Most academies are well under this size.
  let cursor: string | undefined;
  for (let page = 0; page < 20; page += 1) {
    const list = await listAdminStudents({ limit: 100, cursor });
    const hit = list.students.find((s) => s.student_id === studentId);
    if (hit) return hit;
    if (!list.next_cursor) return null;
    cursor = list.next_cursor;
  }
  return null;
}

export interface UpdateAdminStudentRequest {
  full_name?: string;
  status?: "active" | "paused" | "inactive";
  notes?: string | null;
}

/**
 * Patch a student's profile.
 *
 * TODO(wave5-A): the BFF route `/api/v2/admin/students/{id}` is not yet
 * shipped. This helper exists so the detail-edit form has a stable call
 * site; it intentionally surfaces a 404 today.
 */
export function updateAdminStudent(
  studentId: string,
  payload: UpdateAdminStudentRequest,
): Promise<AdminStudentDetail> {
  return apiFetch<AdminStudentDetail>(`/admin/students/${encodeURIComponent(studentId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
