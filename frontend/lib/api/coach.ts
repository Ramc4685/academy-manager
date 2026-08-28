/**
 * Typed coach BFF client.
 *
 * Thin wrapper over apiFetch. When `lib/api/generated/v2.d.ts` lands from
 * `pnpm generate:api`, the types here will be derived from it; for Phase 0
 * we hand-declare them.
 */

import { apiFetch } from "./client";
import {
  coachDayHubPath,
  coachSessionBulkSkillStatusPath,
  coachSessionSkillsPath,
  coachSkillNotesPath,
} from "./coach-paths";

export type EnrollmentStatus = "active" | "paused" | "cancelled";
export type AttendanceStatus = "present" | "absent" | "late";

export interface CoachRosterEntry {
  student_id: string;
  full_name: string;
  enrollment_status: EnrollmentStatus;
  /** Mark already recorded for this occurrence (hydrates state on reload). */
  attendance_status?: AttendanceStatus | null;
  /** True when a parent submitted an absence notice for this occurrence. */
  expected_absence?: boolean;
  /** "enrollment" for regular roster rows; "makeup"/"trial" for one-time entries. */
  entry_source?: "enrollment" | "makeup" | "trial";
}

export interface CoachSession {
  session_id: string;
  occurrence_id: string;
  title: string;
  location: string;
  timezone?: string | null;
  start_at: string;
  end_at: string;
  roster: CoachRosterEntry[];
}

export interface CoachTodayResponse {
  date: string; // YYYY-MM-DD
  sessions: CoachSession[];
}

export interface CoachSkillGap {
  skill_id: string;
  skill_name: string;
  status: string;
  program_id?: string;
  level_id?: string;
}

export interface CoachSkillGroup {
  skill_id: string;
  skill_name: string;
  student_ids: string[];
  student_names: string[];
  status: string;
}

export interface CoachDayHubStudent {
  student_id: string;
  full_name: string;
  enrollment_status: EnrollmentStatus;
  top_gaps: CoachSkillGap[];
}

export interface CoachDayHubSession {
  session_id: string;
  occurrence_id: string;
  title: string;
  location: string;
  timezone?: string | null;
  start_at: string;
  end_at: string;
  roster: CoachRosterEntry[];
  skill_groups: CoachSkillGroup[];
  students: CoachDayHubStudent[];
}

export interface CoachDayHubSummary {
  session_count: number;
  student_count: number;
  attendance_state: "not_started" | "in_progress" | "complete" | "no_sessions" | string;
  skill_focus_count: number;
  parent_message_count: number;
  absence_notice_count: number;
}

export interface CoachDayHubResponse {
  date: string;
  summary: CoachDayHubSummary;
  sessions: CoachDayHubSession[];
}

export interface CoachSessionSkillsStudent {
  student_id: string;
  full_name: string;
  enrollment_status: EnrollmentStatus;
  skills: CoachSkillGap[];
  top_gaps: CoachSkillGap[];
}

export interface CoachSessionSkillsResponse extends CoachDayHubSession {
  date: string | null;
  students: CoachSessionSkillsStudent[];
}

export interface BulkSkillStatusRequest {
  skill_id: string;
  program_id: string;
  level_id: string;
  student_ids: string[];
  status: string;
}

export interface BulkSkillStatusResponse {
  updated: number;
  student_ids: string[];
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

export interface BulkAttendanceEntry {
  student_id: string;
  status: AttendanceStatus;
}

export interface BulkMarkAttendanceRequest {
  mutation_id: string;
  session_id: string;
  entries: BulkAttendanceEntry[];
}

export interface BulkAttendanceEntryResult {
  student_id: string;
  status: AttendanceStatus;
  attendance_id: string;
}

export interface BulkMarkAttendanceResponse {
  results: BulkAttendanceEntryResult[];
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

export interface SkillNote {
  note_id: string;
  student_id: string;
  skill_id: string;
  coach_id: string;
  session_id: string | null;
  body: string;
  created_at: string;
}

export interface CoachScheduleEntry {
  session_id: string;
  occurrence_id: string;
  title: string;
  location: string;
  timezone?: string | null;
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

export async function getCoachToday(
  date?: string,
): Promise<CoachTodayResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiFetch<CoachTodayResponse>(`/coach/today${q}`, { method: "GET" });
}

export async function getCoachDayHub(date?: string): Promise<CoachDayHubResponse> {
  return apiFetch<CoachDayHubResponse>(coachDayHubPath(date), { method: "GET" });
}

export async function getCoachSessionSkills(
  occurrenceId: string,
  options: { date?: string; programId?: string } = {},
): Promise<CoachSessionSkillsResponse> {
  return apiFetch<CoachSessionSkillsResponse>(coachSessionSkillsPath(occurrenceId, options), {
    method: "GET",
  });
}

export async function bulkUpdateCoachSessionSkillStatus(
  occurrenceId: string,
  payload: BulkSkillStatusRequest,
): Promise<BulkSkillStatusResponse> {
  return apiFetch<BulkSkillStatusResponse>(coachSessionBulkSkillStatusPath(occurrenceId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getCoachDashboard(): Promise<CoachDashboardResponse> {
  return apiFetch<CoachDashboardResponse>("/coach/dashboard", {
    method: "GET",
  });
}

export async function markAttendance(
  payload: MarkAttendanceRequest,
): Promise<MarkAttendanceResponse> {
  return apiFetch<MarkAttendanceResponse>("/coach/attendance", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function bulkMarkAttendance(
  occurrenceId: string,
  payload: BulkMarkAttendanceRequest,
): Promise<BulkMarkAttendanceResponse> {
  return apiFetch<BulkMarkAttendanceResponse>(
    `/coach/occurrences/${encodeURIComponent(occurrenceId)}/attendance/bulk`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listLessonPlans(
  sessionId: string,
): Promise<{ plans: LessonPlan[] }> {
  return apiFetch(
    `/coach/sessions/${encodeURIComponent(sessionId)}/lesson-plans`,
    { method: "GET" },
  );
}

export function createLessonPlan(
  sessionId: string,
  payload: { title: string; body: string },
): Promise<LessonPlan> {
  return apiFetch(
    `/coach/sessions/${encodeURIComponent(sessionId)}/lesson-plans`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listProgressNotes(
  sessionId: string,
): Promise<{ notes: ProgressNote[] }> {
  return apiFetch(
    `/coach/sessions/${encodeURIComponent(sessionId)}/progress-notes`,
    { method: "GET" },
  );
}

export function createProgressNote(
  sessionId: string,
  payload: { student_id: string; body: string },
): Promise<ProgressNote> {
  return apiFetch(
    `/coach/sessions/${encodeURIComponent(sessionId)}/progress-notes`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listSkillNotes(
  studentId: string,
  skillId: string,
): Promise<{ notes: SkillNote[] }> {
  return apiFetch(coachSkillNotesPath(studentId, skillId), { method: "GET" });
}

export function createSkillNote(
  studentId: string,
  payload: { skill_id: string; body: string },
): Promise<SkillNote> {
  return apiFetch(coachSkillNotesPath(studentId), {
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

export async function getSessionRoster(
  sessionId: string,
): Promise<RosterResponse> {
  return apiFetch<RosterResponse>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/roster`,
    { method: "GET" },
  );
}

export async function getCoachProfile(): Promise<CoachProfileResponse> {
  return apiFetch<CoachProfileResponse>("/coach/profile", { method: "GET" });
}

export async function updateCoachProfile(
  payload: UpdateCoachProfileRequest,
): Promise<CoachProfileResponse> {
  return apiFetch<CoachProfileResponse>("/coach/profile", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Daily teaching plan (Phase 3: coach lesson guidance)
//
// Shapes mirror the backend DTOs in
// backend/v2/contexts/coaching/application/use_cases/generate_daily_teaching_plan.py
// (serialized via `model_dump(mode="json")`). Hand-declared until the
// openapi-typescript generator lands.
// ---------------------------------------------------------------------------

export interface VideoLink {
  title: string;
  url: string;
}

export type ResourceLinkKind = "YOUTUBE" | "PDF_REFERENCE";

/**
 * A lesson-card resource. `url` is `null` for `PDF_REFERENCE` (citation chip
 * only — the Shuttle Time PDF is not hosted; render as non-interactive text).
 */
export interface ResourceLink {
  kind: ResourceLinkKind;
  title: string;
  url: string | null;
}

export interface LessonCard {
  card_id: string;
  lesson_number: number;
  title: string;
  goal_summary: string;
  teaching_points: string[];
  equipment: string[];
  activity_summary: string;
  safety_notes: string[];
  source: string;
  module_name: string;
  lesson_range: string;
  page_hint: string | null;
  resource_links: ResourceLink[];
}

export type TeachingFocus = "practice" | "review" | "ready_for_level_up";

export interface NextSkill {
  skill_id: string;
  name: string;
  sequence: number;
  level_id: string;
  status: string;
  is_review: boolean;
  criteria: string[];
  youtube_links: VideoLink[];
}

export interface TeachingStudentFocus {
  student_id: string;
  student_name: string;
  /** `null` when `focus === "ready_for_level_up"`. */
  next_skill: NextSkill | null;
  focus: TeachingFocus;
}

export interface TeachingUnplacedStudent {
  student_id: string;
  student_name: string;
}

export interface LevelTeachingGroup {
  level_id: string;
  level_name: string;
  level_sequence: number;
  youtube_links: VideoLink[];
  /** `null` for level-up-ready groups. */
  lesson_card: LessonCard | null;
  students: TeachingStudentFocus[];
}

export interface SessionTeachingPlan {
  session_id: string;
  occurrence_id: string | null;
  title: string;
  location: string;
  start_at: string | null;
  end_at: string | null;
  timezone?: string | null;
  groups: LevelTeachingGroup[];
  unplaced: TeachingUnplacedStudent[];
}

export interface TeachingPlanResponse {
  date: string; // YYYY-MM-DD
  program_id: string;
  program_name: string;
  pathway_configured: boolean;
  sessions: SessionTeachingPlan[];
}

export interface SessionTeachingPlanResponse {
  program_id: string;
  program_name: string;
  pathway_configured: boolean;
  session_id: string;
  groups: LevelTeachingGroup[];
  unplaced: TeachingUnplacedStudent[];
}

/** Coach's teaching plan for every assigned session on a date (default today UTC). */
export async function getCoachTodayPlan(
  date?: string,
): Promise<TeachingPlanResponse> {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiFetch<TeachingPlanResponse>(`/coach/today/plan${q}`, {
    method: "GET",
  });
}

/** Teaching plan for a single session (no title/times — the page already has them). */
export async function getSessionTeachingPlan(
  sessionId: string,
  programId?: string,
): Promise<SessionTeachingPlanResponse> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<SessionTeachingPlanResponse>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/teaching-plan${q}`,
    { method: "GET" },
  );
}

export interface CoachBillingEnrollment {
  enrollment_id: string;
  student_id: string;
  session_type_id: string;
  session_type_name: string;
  status: string;
  billing_start_date: string;
  override_price_cents: number | null;
}

export interface CoachProrationPreview {
  credit_cents: number;
  charge_cents: number;
  net_cents: number;
  from_session_type_id: string | null;
  to_session_type_id: string;
}

/** Billing enrollments for students on a session the coach is assigned to. */
export async function listCoachBillingEnrollments(
  sessionId: string,
): Promise<CoachBillingEnrollment[]> {
  return apiFetch<CoachBillingEnrollment[]>(
    `/coach/billing-enrollments?session_id=${encodeURIComponent(sessionId)}`,
    { method: "GET" },
  );
}

/**
 * Read-only proration preview. The matching coach POST move route is 403 by
 * design, so coach UI must never offer an apply affordance.
 */
export async function previewCoachBillingMove(
  enrollmentId: string,
  toSessionTypeId: string,
  moveDate?: string,
): Promise<CoachProrationPreview> {
  const query = new URLSearchParams({ to_session_type_id: toSessionTypeId });
  if (moveDate) query.set("move_date", moveDate);
  return apiFetch<CoachProrationPreview>(
    `/coach/billing-enrollments/${encodeURIComponent(enrollmentId)}/move/preview?${query.toString()}`,
    { method: "GET" },
  );
}
