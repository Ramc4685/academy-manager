import { apiFetch } from "./client";
import type {
  LevelTeachingGroup,
  TeachingUnplacedStudent,
} from "@/components/teaching/types";

export interface AdminOccurrenceTeachingPlanResponse {
  program_id: string;
  program_name: string;
  pathway_configured: boolean;
  occurrence_id: string;
  session_id: string;
  coach_id: string;
  groups: LevelTeachingGroup[];
  unplaced: TeachingUnplacedStudent[];
}

export interface CoachEngagementStatsRow {
  coach_id: string;
  outcomes_recorded: number;
}

export interface CoachEngagementStatsResponse {
  rows: CoachEngagementStatsRow[];
}

export function getAdminOccurrenceTeachingPlan(
  occurrenceId: string,
  programId?: string | null,
): Promise<AdminOccurrenceTeachingPlanResponse> {
  const q = programId ? `?program_id=${encodeURIComponent(programId)}` : "";
  return apiFetch<AdminOccurrenceTeachingPlanResponse>(
    `/admin/sessions/${encodeURIComponent(occurrenceId)}/teaching-plan${q}`,
    { method: "GET" },
  );
}

export function getCoachEngagementStats(params: {
  startDate: string;
  endDate: string;
}): Promise<CoachEngagementStatsResponse> {
  const q = new URLSearchParams({
    start_date: params.startDate,
    end_date: params.endDate,
  });
  return apiFetch<CoachEngagementStatsResponse>(
    `/admin/progress/coach-engagement?${q.toString()}`,
    { method: "GET" },
  );
}
