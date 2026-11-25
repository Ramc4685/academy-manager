/**
 * Class recap: what one dated class taught, and which present children
 * practised which skill. Coach/owner write it directly or send an after-class
 * report; the parent reads only their own child's view.
 */

import { apiFetch } from "./client";

export interface RecapSkill {
  skill_id: string;
  name: string;
  level_name: string;
}

export interface ChildPractice {
  student_id: string;
  skill_ids: string[];
}

/** recorded: landed and passed; counted: landed as a try short of the
 * skill's N (or the pass was since taken back); in_progress: a save stopped
 * part way and saving again finishes it; earned_before: passed at an earlier
 * date; not_recorded: the skill pipeline did not count it. */
export type PassReceipt =
  | "recorded"
  | "counted"
  | "in_progress"
  | "earned_before"
  | "not_recorded";

export interface ClassPass {
  student_id: string;
  skill_id: string;
}

export interface ChildPassView extends ClassPass {
  receipt: PassReceipt;
  added_revision: number;
}

export interface RecapRosterEntry {
  student_id: string;
  name: string;
  attendance: string;
}

export type ReportOutcome = "applied" | "needs_clarification" | "sent_to_owner";

export interface ClassReport {
  report_id: string;
  is_mine: boolean;
  text: string;
  submitted_at: string;
  outcome: ReportOutcome;
  ai_used: boolean;
  questions: string[];
  pass_claims: { student_id: string; skill_id: string }[];
  applied_revision: number | null;
  resolved_at: string | null;
}

export interface ClassRecapView {
  occurrence_id: string;
  class_starts_at: string;
  can_edit: boolean;
  can_resolve: boolean;
  ai_enabled: boolean;
  revision: number;
  source: string | null;
  updated_at: string | null;
  taught_skills: RecapSkill[];
  practice: ChildPractice[];
  passes: ChildPassView[];
  roster: RecapRosterEntry[];
  skill_options: RecapSkill[];
  reports: ClassReport[];
}

export interface SaveClassRecapBody {
  class_starts_at: string;
  mutation_id: string;
  expected_revision: number;
  taught_skill_ids: string[];
  practice: ChildPractice[];
  /** Every pass of this class: saved ones must stay listed. */
  passes: ClassPass[];
}

export interface SubmitClassReportBody {
  class_starts_at: string;
  report_id: string;
  text: string;
  use_ai: boolean;
}

export interface ClassReportHandoff {
  report_id: string;
  occurrence_id: string;
  class_starts_at: string;
  author_id: string;
  text: string;
  submitted_at: string;
}

export interface ChildRecapSkill {
  skill_id: string;
  name: string;
  /** Passed as of today (the skill pipeline), not necessarily at this class. */
  passed: boolean;
}

export interface ChildClassRecap {
  occurrence_id: string;
  class_starts_at: string;
  taught_skills: ChildRecapSkill[];
  practiced_skills: ChildRecapSkill[];
}

const recapPath = (occurrenceId: string) =>
  `/coach/occurrences/${encodeURIComponent(occurrenceId)}/class-recap`;
const reportsPath = (occurrenceId: string) =>
  `/coach/occurrences/${encodeURIComponent(occurrenceId)}/class-reports`;

export function getClassRecap(occurrenceId: string): Promise<ClassRecapView> {
  return apiFetch<ClassRecapView>(recapPath(occurrenceId), { method: "GET" });
}

export function saveClassRecap(
  occurrenceId: string,
  body: SaveClassRecapBody,
): Promise<ClassRecapView> {
  return apiFetch<ClassRecapView>(recapPath(occurrenceId), {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function submitClassReport(
  occurrenceId: string,
  body: SubmitClassReportBody,
): Promise<ClassReport> {
  return apiFetch<ClassReport>(reportsPath(occurrenceId), {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function resolveClassReport(occurrenceId: string, reportId: string): Promise<ClassReport> {
  return apiFetch<ClassReport>(
    `${reportsPath(occurrenceId)}/${encodeURIComponent(reportId)}/resolve`,
    { method: "POST" },
  );
}

export function listClassReportHandoffs(): Promise<{ reports: ClassReportHandoff[] }> {
  return apiFetch<{ reports: ClassReportHandoff[] }>("/admin/class-reports/handoffs", {
    method: "GET",
  });
}

export function listChildClassRecaps(studentId: string): Promise<{ recaps: ChildClassRecap[] }> {
  return apiFetch<{ recaps: ChildClassRecap[] }>(
    `/parent/students/${encodeURIComponent(studentId)}/class-recaps`,
    { method: "GET" },
  );
}
