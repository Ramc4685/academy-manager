/**
 * The AI-drafted note for tonight's parent email (AI Phase 2, B4).
 *
 * Pure helpers for the coach's tap-skills workspace: who earned a note today,
 * and the one sentence shown for each way the draft can fail. No React.
 */

import type { ApiError } from "@/lib/api/client";
import type { SkillBoardCell } from "@/lib/api/curriculum";
import { parseAcademyInstant } from "@/lib/format/academy-time";

/** B1's GET /admin/ai/status; the button only shows when it says enabled. */
export const AI_STATUS_KEY = ["admin", "ai", "status"] as const;

function localDateKey(d: Date): string {
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${month}-${day}`;
}

/** Whether any skill in `statuses` was passed on `date` (YYYY-MM-DD, device-local day). */
export function masteredOn(statuses: Record<string, SkillBoardCell>, date: string): boolean {
  return Object.values(statuses).some(
    (cell) =>
      cell.status === "PASSED" &&
      !!cell.last_updated_at &&
      localDateKey(parseAcademyInstant(cell.last_updated_at)) === date,
  );
}

const ERROR_COPY: Record<number, string> = {
  503: "AI notes are not enabled for this academy yet",
  403: "AI notes are part of the Growth plan",
  429: "This academy has used its AI drafts for the month",
  502: "The note could not be read, try again",
  409: "Nothing mastered that day to write about",
};

/** One plain sentence per failure; never a crash. */
export function narrativeErrorCopy(error: unknown): string {
  const status = (error as Partial<ApiError> | null)?.status;
  return (status !== undefined && ERROR_COPY[status]) || "Couldn't draft the note. Try again.";
}
