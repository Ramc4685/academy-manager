/**
 * Typed coach BFF client.
 *
 * Thin wrapper over apiFetch. When `lib/api/generated/v2.d.ts` lands from
 * `pnpm generate:api`, the types here will be derived from it; for Phase 0
 * we hand-declare them.
 */

import { apiFetch } from "./client";

export type EnrollmentStatus = "active" | "paused" | "cancelled";
export type AttendanceStatus = "present" | "absent" | "late";

export interface CoachRosterEntry {
  student_id: string;
  full_name: string;
  enrollment_status: EnrollmentStatus;
}

export interface CoachSession {
  session_id: string;
  title: string;
  location: string;
  start_at: string;
  end_at: string;
  roster: CoachRosterEntry[];
}

export interface CoachTodayResponse {
  date: string; // YYYY-MM-DD
  sessions: CoachSession[];
}

export interface MarkAttendanceRequest {
  mutation_id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  marked_at_client?: string;
  client_app_version?: string;
}

export interface MarkAttendanceResponse {
  attendance_id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  marked_at: string;
}

export async function getCoachToday(date?: string): Promise<CoachTodayResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiFetch<CoachTodayResponse>(`/coach/today${q}`, { method: "GET" });
}

export async function markAttendance(
  payload: MarkAttendanceRequest
): Promise<MarkAttendanceResponse> {
  return apiFetch<MarkAttendanceResponse>("/coach/attendance", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
