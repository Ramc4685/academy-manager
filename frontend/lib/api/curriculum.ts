/**
 * Typed curriculum + student-progress BFF client.
 *
 * Covers two bounded contexts:
 *   - curriculum   — programs, levels, skills (admin configures)
 *   - student_progress — skill tracking, test attempts, certificates
 *
 * Types are hand-declared until the openapi-typescript generator produces
 * lib/api/generated/v2.d.ts.
 */

import { apiFetch } from "./client";
import { coachStudentPassportPath } from "./coach-paths";

// ---------------------------------------------------------------------------
// Curriculum types
// ---------------------------------------------------------------------------

export interface Program {
  program_id: string;
  name: string;
  sport: string;
  description: string;
  is_active: boolean;
}

export interface Level {
  level_id: string;
  program_id: string;
  sequence: number;
  name: string;
  description: string;
  completion_rule: string;
  requires_coach_recommendation: boolean;
  requires_admin_approval: boolean;
  is_active: boolean;
}

export interface Skill {
  skill_id: string;
  level_id: string;
  sequence: number;
  name: string;
  description: string;
  is_required: boolean;
  scoring_type: string;
  pass_threshold_pct: number;
  is_active: boolean;
}

export interface SkillCriterion {
  criterion_id: string;
  skill_id: string;
  description: string;
  display_order: number;
}

export interface PathwayLevel {
  level: Level;
  skills: { skill: Skill; criteria: SkillCriterion[] }[];
}

export interface FullPathway {
  program: Program;
  levels: PathwayLevel[];
}

// ---------------------------------------------------------------------------
// Student progress types
// ---------------------------------------------------------------------------

export type SkillStatus =
  | "NOT_STARTED"
  | "INTRODUCED"
  | "LEARNING"
  | "PRACTICING"
  | "TEST_READY"
  | "PASSED"
  | "NEEDS_REVIEW";

export interface SkillPassportEntry {
  skill_id: string;
  level_id: string;
  program_id: string;
  skill_name: string;
  skill_description: string;
  sequence: number;
  is_required: boolean;
  status: SkillStatus;
  last_test_passed: boolean | null;
  last_tested_at: string | null;
  test_attempt_count: number;
}

export interface StudentSkillProgress {
  skill_progress_id: string;
  student_id: string;
  skill_id: string;
  level_id: string;
  program_id: string;
  status: SkillStatus;
  introduced_at: string | null;
  last_updated_at: string;
  last_updated_by: string;
}

export interface RecordTestAttemptResult {
  attempt_id: string;
  passed: boolean;
  score: number;
  skill_status: SkillStatus;
  level_completed: boolean;
}

export interface StudentProgressSummary {
  student_id: string;
  program_id: string;
  program_name: string;
  current_level_id: string | null;
  current_level_name: string | null;
  current_level_sequence: number | null;
  total_skills: number;
  passed_skills: number;
  in_progress_skills: number;
  not_started_skills: number;
  level_up_status: string | null;
}

export type ProgressNextAction =
  | "place_in_level"
  | "continue_practice"
  | "record_tests"
  | "recommend_level_up"
  | "awaiting_admin_approval"
  | "certificate_issued";

export type LevelCompletionStatus =
  | "not_started"
  | "in_progress"
  | "test_ready"
  | "complete";

export interface StudentProgressOverview {
  student_id: string;
  student_name: string;
  program_id: string;
  program_name: string;
  current_level_id: string | null;
  current_level_name: string | null;
  current_level_sequence: number | null;
  required_skill_count: number;
  required_skills_passed: number;
  total_skill_count: number;
  total_skills_passed: number;
  in_progress_count: number;
  not_started_count: number;
  test_ready_count: number;
  level_completion_status: LevelCompletionStatus;
  level_up_status: string | null;
  certificate_count: number;
  next_action: ProgressNextAction;
}

export interface LevelUpRecommendation {
  rec_id: string;
  student_id: string;
  from_level_id: string;
  to_level_id: string;
  program_id: string;
  status: string;
  recommended_by: string;
  recommended_at: string;
}

export interface SkillCertificate {
  cert_id: string;
  student_id: string;
  cert_number: string;
  student_name: string;
  level_name: string;
  program_name: string;
  completed_at: string;
  issued_at: string;
}

// ---------------------------------------------------------------------------
// Admin — curriculum
// ---------------------------------------------------------------------------

export function listPrograms(academyId: string): Promise<Program[]> {
  return apiFetch<{ programs: Program[] }>(
    `/admin/programs?academy_id=${encodeURIComponent(academyId)}`,
    { method: "GET" },
  ).then((d) => d.programs);
}

export function createProgram(body: {
  name: string;
  sport: string;
  description: string;
}): Promise<Program> {
  return apiFetch<Program>("/admin/programs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getFullPathway(programId: string): Promise<FullPathway> {
  return apiFetch<FullPathway>(
    `/admin/programs/${encodeURIComponent(programId)}/pathway`,
    { method: "GET" },
  );
}

export function createLevel(
  programId: string,
  body: {
    name: string;
    description: string;
    sequence: number;
    completion_rule?: string;
  },
): Promise<Level> {
  return apiFetch<Level>(
    `/admin/programs/${encodeURIComponent(programId)}/levels`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function createSkill(
  levelId: string,
  body: {
    name: string;
    description: string;
    is_required: boolean;
    scoring_type: string;
    pass_threshold_pct?: number;
  },
): Promise<Skill> {
  return apiFetch<Skill>(
    `/admin/levels/${encodeURIComponent(levelId)}/skills`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

// ---------------------------------------------------------------------------
// Admin — lesson cards
// ---------------------------------------------------------------------------

export interface LessonCardSummary {
  card_id: string;
  slug: string;
  lesson_number: number;
  title: string;
  module_name: string;
  lesson_range: string;
  skill_ids: string[];
}

export interface LessonCardsList {
  count: number;
  cards: LessonCardSummary[];
}

export interface SeedLessonCardsResult {
  program_id: string;
  cards_created: number;
  cards_updated: number;
  cards_unchanged: number;
  video_refs_created: number;
  video_refs_updated: number;
  video_refs_unchanged: number;
}

export function listLessonCards(programId: string): Promise<LessonCardsList> {
  return apiFetch<LessonCardsList>(
    `/admin/programs/${encodeURIComponent(programId)}/lesson-cards`,
    { method: "GET" },
  );
}

export function seedLessonCards(programId: string): Promise<SeedLessonCardsResult> {
  return apiFetch<SeedLessonCardsResult>(
    `/admin/programs/${encodeURIComponent(programId)}/lesson-cards/seed`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Admin — student progress
// ---------------------------------------------------------------------------

export function placeStudentInLevel(
  studentId: string,
  body: { program_id?: string; level_id: string },
): Promise<{ placed: boolean }> {
  return apiFetch<{ placed: boolean }>(
    `/admin/students/${encodeURIComponent(studentId)}/pathway-placement`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function getStudentProgress(
  studentId: string,
  programId: string,
): Promise<StudentProgressSummary> {
  return apiFetch<StudentProgressSummary>(
    `/admin/students/${encodeURIComponent(studentId)}/progress?program_id=${encodeURIComponent(programId)}`,
    { method: "GET" },
  );
}

export function getAdminStudentPassport(
  studentId: string,
  programId?: string,
): Promise<SkillPassportEntry[]> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<{ passport: SkillPassportEntry[] }>(
    `/admin/students/${encodeURIComponent(studentId)}/passport${q}`,
    { method: "GET" },
  ).then((d) => d.passport);
}

export function updateAdminSkillStatus(
  studentId: string,
  skillId: string,
  body: { program_id: string; level_id: string; status: SkillStatus },
): Promise<StudentSkillProgress> {
  return apiFetch<StudentSkillProgress>(
    `/admin/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/status`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function recordAdminTestAttempt(
  studentId: string,
  skillId: string,
  body: {
    program_id: string;
    level_id: string;
    attempts_count: number;
    success_count: number;
    notes?: string;
    session_id?: string;
  },
): Promise<RecordTestAttemptResult> {
  return apiFetch<RecordTestAttemptResult>(
    `/admin/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/test`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function getLevelUpQueue(programId?: string): Promise<LevelUpRecommendation[]> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<{ queue: LevelUpRecommendation[] }>(`/admin/level-up-queue${q}`, {
    method: "GET",
  }).then((d) => d.queue);
}

export function approveLevelUp(recId: string): Promise<{ approved: boolean }> {
  return apiFetch<{ approved: boolean }>(
    `/admin/level-up/${encodeURIComponent(recId)}/approve`,
    { method: "POST" },
  );
}

export function rejectLevelUp(
  recId: string,
  reason: string,
): Promise<{ rejected: boolean }> {
  return apiFetch<{ rejected: boolean }>(
    `/admin/level-up/${encodeURIComponent(recId)}/reject`,
    { method: "POST", body: JSON.stringify({ rejection_reason: reason }) },
  );
}

export function getAdminStudentCertificates(studentId: string): Promise<SkillCertificate[]> {
  return apiFetch<{ certificates: SkillCertificate[] }>(
    `/admin/students/${encodeURIComponent(studentId)}/certificates`,
    { method: "GET" },
  ).then((d) => d.certificates);
}

// ---------------------------------------------------------------------------
// Progress overview
// ---------------------------------------------------------------------------

export function getAdminPathwayProgress(
  programId: string,
  nextAction?: ProgressNextAction,
): Promise<StudentProgressOverview[]> {
  const params = new URLSearchParams({ program_id: programId });
  if (nextAction) params.set("next_action", nextAction);
  return apiFetch<{ rows: StudentProgressOverview[] }>(
    `/admin/pathway/progress?${params.toString()}`,
    { method: "GET" },
  ).then((d) => d.rows);
}

export function getCoachSessionStudentsProgress(
  sessionId: string,
  programId?: string,
): Promise<StudentProgressOverview[]> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<{ rows: StudentProgressOverview[] }>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/students-progress${q}`,
    { method: "GET" },
  ).then((d) => d.rows);
}

export function getParentProgressSummary(
  programId?: string,
): Promise<StudentProgressOverview[]> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<{ rows: StudentProgressOverview[] }>(
    `/parent/progress/summary${q}`,
    { method: "GET" },
  ).then((d) => d.rows);
}

// ---------------------------------------------------------------------------
// Coach
// ---------------------------------------------------------------------------

export function getStudentPassport(
  studentId: string,
  programId?: string,
): Promise<SkillPassportEntry[]> {
  return apiFetch<{ passport: SkillPassportEntry[] }>(
    coachStudentPassportPath(studentId, programId),
    { method: "GET" },
  ).then((d) => d.passport);
}

export function updateSkillStatus(
  studentId: string,
  skillId: string,
  body: { program_id: string; level_id: string; status: SkillStatus },
): Promise<{ updated: boolean }> {
  return apiFetch<{ updated: boolean }>(
    `/coach/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/status`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function recordTestAttempt(
  studentId: string,
  skillId: string,
  body: {
    program_id: string;
    level_id: string;
    attempts_count: number;
    success_count: number;
    notes?: string;
    session_id?: string;
  },
): Promise<{ recorded: boolean }> {
  return apiFetch<{ recorded: boolean }>(
    `/coach/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/test`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function recommendLevelUp(
  studentId: string,
  programId?: string,
): Promise<LevelUpRecommendation> {
  return apiFetch<LevelUpRecommendation>(
    `/coach/students/${encodeURIComponent(studentId)}/level-up`,
    { method: "POST", body: JSON.stringify(programId ? { program_id: programId } : {}) },
  );
}

// ---------------------------------------------------------------------------
// Parent
// ---------------------------------------------------------------------------

export function getParentStudentPassport(
  studentId: string,
  programId?: string,
): Promise<SkillPassportEntry[]> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<{ passport: SkillPassportEntry[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/skill-progress${q}`,
    { method: "GET" },
  ).then((d) => d.passport);
}

export function getParentStudentCertificates(studentId: string): Promise<SkillCertificate[]> {
  return apiFetch<{ certificates: SkillCertificate[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/certificates`,
    { method: "GET" },
  ).then((d) => d.certificates);
}

// ---------------------------------------------------------------------------
// Session skill board
// ---------------------------------------------------------------------------

export interface SkillBoardCell {
  status: SkillStatus;
  last_updated_at: string | null;
}

export interface SkillBoardSkill {
  skill_id: string;
  name: string;
  sequence: number;
  is_required: boolean;
}

export interface SkillBoardStudentRow {
  student_id: string;
  student_name: string;
  statuses: Record<string, SkillBoardCell>;
  required_passed: number;
  required_total: number;
  total_passed: number;
  total_count: number;
  level_up_status: string | null;
}

export interface SkillBoardLevelGroup {
  level_id: string;
  level_name: string;
  sequence: number;
  skills: SkillBoardSkill[];
  students: SkillBoardStudentRow[];
}

export interface SkillBoard {
  program_id: string;
  program_name: string;
  groups: SkillBoardLevelGroup[];
  unplaced: { student_id: string; student_name: string }[];
}

export function getAdminSessionSkillBoard(
  sessionId: string,
  programId?: string,
): Promise<SkillBoard> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<SkillBoard>(
    `/admin/sessions/${encodeURIComponent(sessionId)}/skill-board${q}`,
    { method: "GET" },
  );
}

export function getCoachSessionSkillBoard(
  sessionId: string,
  programId?: string,
): Promise<SkillBoard> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<SkillBoard>(
    `/coach/sessions/${encodeURIComponent(sessionId)}/skill-board${q}`,
    { method: "GET" },
  );
}
