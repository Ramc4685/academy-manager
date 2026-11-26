import type { AdminStudentAttendanceView } from "@/lib/api/admin";

export const FORMER_STUDENT = "Former student";

export interface OccurrenceAttendanceRow {
  studentId: string;
  name: string;
  /** Null: on the roster, no mark yet (S25: the admin can give one). */
  mark: AdminStudentAttendanceView | null;
}

/**
 * S25: every child on the class date, one row each. Marked children first (in
 * mark order), named by the server (it resolves former students); then ACTIVE
 * roster children with no mark, so an admin can give them one. Past enrollments
 * only name existing marks: a withdrawn child is not offered a mark. Never a raw id.
 */
export function occurrenceAttendanceRows(
  marks: AdminStudentAttendanceView[],
  rosterNameById: Map<string, string>,
  activeNameById: Map<string, string>,
): OccurrenceAttendanceRow[] {
  const marked = new Set(marks.map((mark) => mark.student_id));
  return [
    ...marks.map((mark) => ({
      studentId: mark.student_id,
      name: mark.student_name || rosterNameById.get(mark.student_id) || FORMER_STUDENT,
      mark,
    })),
    ...[...activeNameById]
      .filter(([studentId]) => !marked.has(studentId))
      .map(([studentId, name]) => ({ studentId, name, mark: null })),
  ];
}
