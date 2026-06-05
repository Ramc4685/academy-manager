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
  skill_name: string;
  skill_description: string;
  sequence: number;
  is_required: boolean;
  status: SkillStatus;
  last_test_passed: boolean | null;
  last_tested_at: string | null;
  test_attempt_count: number;
}

export interface StudentProgressSummary {
  student_id: string;
  program_id: string;
  program_name: string;
  current_level_name: string | null;
  total_skills: number;
  passed_skills: number;
  in_progress_skills: number;
  not_started_skills: number;
  level_up_status: string | null;
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

export function seedBadminton(programId: string): Promise<{ seeded: boolean }> {
  return apiFetch<{ seeded: boolean }>(
    `/admin/programs/${encodeURIComponent(programId)}/seed-badminton`,
    { method: "POST" },
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
// Admin — student progress
// ---------------------------------------------------------------------------

export function placeStudentInLevel(
  studentId: string,
  body: { program_id: string; level_id: string },
): Promise<{ placed: boolean }> {
  return apiFetch<{ placed: boolean }>(
    `/admin/students/${encodeURIComponent(studentId)}/place-in-level`,
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
    { method: "POST", body: JSON.stringify({ reason }) },
  );
}

export function getAdminStudentCertificates(studentId: string): Promise<SkillCertificate[]> {
  return apiFetch<{ certificates: SkillCertificate[] }>(
    `/admin/students/${encodeURIComponent(studentId)}/certificates`,
    { method: "GET" },
  ).then((d) => d.certificates);
}

// ---------------------------------------------------------------------------
// Coach
// ---------------------------------------------------------------------------

export function getStudentPassport(
  studentId: string,
  programId: string,
): Promise<SkillPassportEntry[]> {
  return apiFetch<{ passport: SkillPassportEntry[] }>(
    `/coach/students/${encodeURIComponent(studentId)}/passport?program_id=${encodeURIComponent(programId)}`,
    { method: "GET" },
  ).then((d) => d.passport);
}

export function updateSkillStatus(
  studentId: string,
  skillId: string,
  status: SkillStatus,
): Promise<{ updated: boolean }> {
  return apiFetch<{ updated: boolean }>(
    `/coach/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/status`,
    { method: "POST", body: JSON.stringify({ status }) },
  );
}

export function recordTestAttempt(
  studentId: string,
  skillId: string,
  body: {
    attempts_count: number;
    success_count: number;
    notes?: string;
    scoring_type: string;
  },
): Promise<{ recorded: boolean }> {
  return apiFetch<{ recorded: boolean }>(
    `/coach/students/${encodeURIComponent(studentId)}/skills/${encodeURIComponent(skillId)}/test`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export function recommendLevelUp(
  studentId: string,
  programId: string,
): Promise<LevelUpRecommendation> {
  return apiFetch<LevelUpRecommendation>(
    `/coach/students/${encodeURIComponent(studentId)}/level-up`,
    { method: "POST", body: JSON.stringify({ program_id: programId }) },
  );
}

// ---------------------------------------------------------------------------
// Parent
// ---------------------------------------------------------------------------

export function getParentStudentPassport(
  studentId: string,
  programId: string,
): Promise<SkillPassportEntry[]> {
  return apiFetch<{ passport: SkillPassportEntry[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/skill-progress?program_id=${encodeURIComponent(programId)}`,
    { method: "GET" },
  ).then((d) => d.passport);
}

export function getParentStudentCertificates(studentId: string): Promise<SkillCertificate[]> {
  return apiFetch<{ certificates: SkillCertificate[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/certificates`,
    { method: "GET" },
  ).then((d) => d.certificates);
}
