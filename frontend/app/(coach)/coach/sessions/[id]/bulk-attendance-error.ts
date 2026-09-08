/**
 * Readable message for a rejected "Mark all present" batch (issue #672).
 *
 * The bulk endpoint rejects the whole batch with 422
 * `Coaching.BulkStudentNotEnrolled` when any row is not eligible for the
 * occurrence — not actively enrolled and holding no approved make-up / trial
 * entry for that date. `details.student_ids` names every such student, so the
 * coach can see who blocked the batch instead of a bare failure.
 */

export const BULK_NOT_ENROLLED_CODE = "Coaching.BulkStudentNotEnrolled";

export interface BulkAttendanceRejection {
  /** Students the server refused; the rest of the batch was NOT saved either. */
  ineligibleIds: string[];
  /** Banner text naming the students. */
  message: string;
}

interface NamedStudent {
  student_id: string;
  full_name: string;
}

function readIneligibleIds(err: unknown): string[] | null {
  const apiError = err as { status?: number; code?: string; details?: Record<string, unknown> };
  if (apiError.code !== BULK_NOT_ENROLLED_CODE) return null;
  const raw = apiError.details?.student_ids;
  if (!Array.isArray(raw)) return [];
  return raw.filter((id): id is string => typeof id === "string");
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * Null when `err` is not the bulk not-enrolled rejection (callers fall back
 * to the generic attendance error). Otherwise the ids and a sentence naming
 * the students by roster name (falling back to the id when the roster no
 * longer lists them).
 */
export function formatBulkAttendanceError(
  err: unknown,
  roster: NamedStudent[],
): BulkAttendanceRejection | null {
  const ineligibleIds = readIneligibleIds(err);
  if (ineligibleIds === null) return null;
  const nameById = new Map(roster.map((s) => [s.student_id, s.full_name]));
  const names = ineligibleIds.map((id) => nameById.get(id) ?? id);
  if (names.length === 0) {
    return {
      ineligibleIds,
      message:
        "Nothing was saved: someone on this roster isn't eligible for attendance today. Refresh the roster and mark the class again.",
    };
  }
  const subject = joinNames(names);
  const verb = names.length === 1 ? "isn't" : "aren't";
  return {
    ineligibleIds,
    message: `Nothing was saved: ${subject} ${verb} eligible for attendance today (not actively enrolled, and no approved make-up or trial for this class). Ask the admin to check their status, then mark the others.`,
  };
}
