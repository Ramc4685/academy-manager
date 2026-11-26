import type { Route } from "next";

import type { AdminStudentRecentAttendance } from "@/lib/api/v2/students";
import { formatAcademyDateTime } from "@/lib/format/academy-time";

export function describeAttendanceClass(row: AdminStudentRecentAttendance) {
  const when = row.class_start_at
    ? formatAcademyDateTime(row.class_start_at, row.class_timezone)
    : "";
  const label = row.class_title ?? "Class details unavailable";
  const href = row.class_session_id && row.occurrence_id
    ? (`/admin/sessions/${encodeURIComponent(row.class_session_id)}?tab=dates&occurrence=${encodeURIComponent(row.occurrence_id)}` as Route)
    : null;

  return { label, when, href };
}
