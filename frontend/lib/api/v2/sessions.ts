import { apiFetch } from "../client";

export interface UpdateCoachAttendanceInput {
  coach_id: string;
  status: "present" | "absent";
  role?: "lead" | "assistant";
  rate_override_minor?: number | null;
  note?: string;
}

export interface UpdateSessionCoachInput {
  actual_coach_id?: string | null;
  substitute_coach_id?: string | null;
  reason: string; // required at the API level
}

export interface UpdateOccurrenceReplacementInput {
  replacement_coach_id?: string | null;
  reason?: string | null;
}

export async function updateOccurrenceCoachAttendance(
  occurrenceId: string, input: UpdateCoachAttendanceInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach-attendance`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function updateSessionOccurrenceCoach(
  occurrenceId: string, input: UpdateSessionCoachInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/coach`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export async function updateOccurrenceReplacement(
  occurrenceId: string, input: UpdateOccurrenceReplacementInput,
): Promise<unknown> {
  return apiFetch(
    `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/replacement`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}
