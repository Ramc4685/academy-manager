/**
 * Student BFF client (UIM12).
 *
 * Thin wrapper over `apiFetch`, mirroring `lib/api/parent.ts`'s shape.
 * Every call hits `/student/*`, which 404s server-side when
 * `enable_student_login` is off or the caller isn't a `student` — there is
 * no separate frontend flag check, the backend is the single source of
 * truth for the gate.
 */

import { apiFetch } from "./client";
import type { SkillPassportEntry } from "./curriculum";

export interface StudentScheduleEntry {
  occurrence_id: string;
  session_id: string;
  session_title: string;
  location: string | null;
  start_at: string;
  end_at: string;
  status: string;
  coach_name: string | null;
}

export interface StudentScheduleResponse {
  entries: StudentScheduleEntry[];
  total: number;
  limit: number;
  offset: number;
}

export function getMySchedule(): Promise<StudentScheduleResponse> {
  return apiFetch("/student/schedule", { method: "GET" });
}

export interface StudentProgressResponse {
  passport: SkillPassportEntry[];
}

export function getMyProgress(): Promise<StudentProgressResponse> {
  return apiFetch("/student/progress", { method: "GET" });
}

export interface StudentProfile {
  student_id: string;
  full_name: string;
  academy_id: string;
  academy_name: string;
  level: string | null;
}

export function getMyProfile(): Promise<StudentProfile> {
  return apiFetch("/student/me", { method: "GET" });
}
