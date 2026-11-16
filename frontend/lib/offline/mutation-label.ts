import type { QueuedMutation } from "./queue";

/**
 * Plain-language label for a queued mutation (issue #841).
 *
 * The Needs-review tray used to read "Mark present for stu-204 in sess-101" —
 * the payload's ids, which a coach has never seen and cannot act on. Marks
 * queued from the session screen now carry `labels` (the student's name and
 * the class title, captured on the device at the moment of the tap), so the
 * tray can name them.
 *
 * Rows already sitting in a coach's IndexedDB from before that change have no
 * labels. They fall back to a neutral phrase rather than the ids: an id in the
 * tray is noise at best, and the row's reason line plus the session it came
 * from is what the coach actually resolves it by.
 */
export function describeQueuedMutation(m: QueuedMutation): string {
  const payload = m.payload as { status?: unknown };
  const status = typeof payload.status === "string" ? payload.status : null;
  const student = m.labels?.student_full_name?.trim();
  const session = m.labels?.session_title?.trim();

  if (student && status) {
    return session
      ? `Marked ${student} ${status} in ${session}`
      : `Marked ${student} ${status}`;
  }
  if (student) return session ? `Attendance mark for ${student} in ${session}` : `Attendance mark for ${student}`;
  if (status) return `Attendance mark (${status})`;
  return "Attendance mark";
}

export interface AttendanceConflict {
  occurrence_id: string;
  student_id: string;
  /** What the server holds (docs/offline-policy.md case #4). */
  recorded: string;
  /** What this device queued. */
  mine: string;
}

/**
 * The two marks a coach chooses between when a queued mark met one already
 * recorded (another device, or an earlier send). Null for any other tray row,
 * or for a conflict from before the server named the recorded status.
 */
export function attendanceConflict(m: QueuedMutation): AttendanceConflict | null {
  if (m.error?.code !== "Coaching.ConflictAttendanceExists") return null;
  const payload = m.payload as { occurrence_id?: unknown; student_id?: unknown; status?: unknown };
  const recorded = m.error.details?.existing_status;
  if (
    typeof recorded !== "string" ||
    // An admin void cannot be overridden by a coach correction: plain Retry/Dismiss.
    recorded === "voided" ||
    typeof payload.occurrence_id !== "string" ||
    typeof payload.student_id !== "string" ||
    typeof payload.status !== "string"
  ) {
    return null;
  }
  return {
    occurrence_id: payload.occurrence_id,
    student_id: payload.student_id,
    recorded,
    mine: payload.status,
  };
}
