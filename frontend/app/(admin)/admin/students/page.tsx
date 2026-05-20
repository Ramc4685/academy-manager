"use client";

import { useQuery } from "@tanstack/react-query";

import { listAdminStudents, type AdminStudentView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Avatar } from "@/components/ds/avatar";

export default function AdminStudentsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.students(),
    queryFn: listAdminStudents,
  });

  return (
    <section data-testid="admin-students" className="space-y-6">
      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load students.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : (data?.students.length ?? 0) === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-students-empty">
          No students registered yet.
        </p>
      ) : (
        <Card p={20}>
          <StudentsTable students={data!.students} />
        </Card>
      )}
    </section>
  );
}

function mapStatus(s: string): any {
  if (s === "active") return "enrolled";
  if (s === "paused") return "paused";
  if (s === "inactive") return "expired";
  return "manual";
}

function StudentsTable({ students }: { students: AdminStudentView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Parent</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Active sessions</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Attendance rate</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Last attendance</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
          </tr>
        </thead>
        <tbody>
          {students.map((student) => (
            <tr key={student.student_id} data-testid={`admin-students-row-${student.student_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-3">
                <div className="flex items-center gap-3">
                  <Avatar name={student.full_name} size={32} />
                  <div>
                    <div className="font-medium text-rally-base">{student.full_name}</div>
                    <div className="font-mono text-[10px] text-rally-subtle">{student.student_id}</div>
                  </div>
                </div>
              </td>
              <td className="px-2 py-3">
                <div className="text-rally-base">{student.parent_name || student.parent_email || "—"}</div>
                {student.parent_email && student.parent_name && (
                  <div className="font-mono text-[10px] text-rally-subtle">{student.parent_email}</div>
                )}
              </td>
              <td className="px-2 py-3 text-right font-mono tabular-nums text-rally-base">{student.active_session_count}</td>
              <td className="px-2 py-3 text-right font-mono tabular-nums text-rally-subtle">—</td>
              <td className="px-2 py-3 text-rally-subtle">
                {student.last_seen_at ? new Date(student.last_seen_at).toLocaleDateString() : "—"}
              </td>
              <td className="px-2 py-3">
                <Chip variant={mapStatus(student.status)} label={student.status.toUpperCase()} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
