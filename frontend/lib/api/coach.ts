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
  occurrence_id: string;
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

export interface CoachDashboardResponse {
  active_student_count: number;
  sessions_today: number;
  attendance_percentage: number;
  expected_cut_cents: number;
  marked_attendance_count: number;
}

export interface MarkAttendanceRequest {
  mutation_id: string;
  occurrence_id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  marked_at_client?: string;
  client_app_version?: string;
}

export interface MarkAttendanceResponse {
  attendance_id: string;
  occurrence_id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  marked_at: string;
}

export interface LessonPlan {
  lesson_plan_id: string;
  session_id: string;
  coach_id: string;
  title: string;
  body: string;
  created_at: string;
}

export interface ProgressNote {
  note_id: string;
  session_id: string;
  student_id: string;
  coach_id: string;
  body: string;
  created_at: string;
}

export interface CoachScheduleEntry {
  session_id: string;
  title: string;
  location: string;
  start_at: string;
  end_at: string;
}

export interface CoachScheduleResponse {
  sessions: CoachScheduleEntry[];
}

export interface CoachProfileResponse {
  user_id: string;
  display_name: string;
  email: string;
  phone: string | null;
}

export interface UpdateCoachProfileRequest {
  display_name?: string | null;
  phone?: string | null;
  email?: string | null;
}

export async function getCoachToday(date?: string): Promise<CoachTodayResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiFetch<CoachTodayResponse>(`/coach/today${q}`, { method: "GET" });
}

export async function getCoachDashboard(): Promise<CoachDashboardResponse> {
  return apiFetch<CoachDashboardResponse>("/coach/dashboard", { method: "GET" });
}

export async function markAttendance(
  payload: MarkAttendanceRequest
): Promise<MarkAttendanceResponse> {
  return apiFetch<MarkAttendanceResponse>("/coach/attendance", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listLessonPlans(sessionId: string): Promise<{ plans: LessonPlan[] }> {
  return apiFetch(`/coach/sessions/${sessionId}/lesson-plans`, { method: "GET" });
}

export function createLessonPlan(
  sessionId: string,
  payload: { title: string; body: string }
): Promise<LessonPlan> {
  return apiFetch(`/coach/sessions/${sessionId}/lesson-plans`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listProgressNotes(sessionId: string): Promise<{ notes: ProgressNote[] }> {
  return apiFetch(`/coach/sessions/${sessionId}/progress-notes`, { method: "GET" });
}

export function createProgressNote(
  sessionId: string,
  payload: { student_id: string; body: string }
): Promise<ProgressNote> {
  return apiFetch(`/coach/sessions/${sessionId}/progress-notes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getCoachSchedule(): Promise<CoachScheduleResponse> {
  return apiFetch<CoachScheduleResponse>("/coach/sessions", { method: "GET" });
}

export interface RosterEntry {
  enrollment_id: string;
  student_id: string;
  full_name: string;
  enrollment_status: string;
}

export interface RosterResponse {
  roster: RosterEntry[];
}

export async function getSessionRoster(sessionId: string): Promise<RosterResponse> {
  return apiFetch<RosterResponse>(`/coach/sessions/${sessionId}/roster`, { method: "GET" });
}

export async function getCoachProfile(): Promise<CoachProfileResponse> {
  return apiFetch<CoachProfileResponse>("/coach/profile", { method: "GET" });
}

export async function updateCoachProfile(
  payload: UpdateCoachProfileRequest
): Promise<CoachProfileResponse> {
  return apiFetch<CoachProfileResponse>("/coach/profile", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
