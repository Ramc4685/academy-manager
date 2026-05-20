"use client";

import { useQuery } from "@tanstack/react-query";

import { listAdminStudents, type AdminStudentView } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

export default function AdminStudentsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.students(),
    queryFn: listAdminStudents,
  });

  return (
    <section data-testid="admin-students">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Students</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Registered children, parent links, attendance recency, and active sessions.
        </p>
      </div>

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load students.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : (data?.students.length ?? 0) === 0 ? (
        <p className="text-sm text-neutral-500">No students registered yet.</p>
      ) : (
        <StudentsTable students={data!.students} />
      )}
    </section>
  );
}

function StudentsTable({ students }: { students: AdminStudentView[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
            <th className="px-4 py-3 font-medium">Student</th>
            <th className="px-4 py-3 font-medium">Parent</th>
            <th className="px-4 py-3 font-medium text-right">Active sessions</th>
            <th className="px-4 py-3 font-medium">Last attendance</th>
            <th className="px-4 py-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {students.map((student) => (
            <tr key={student.student_id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-4 py-3">
                <div className="font-medium">{student.full_name}</div>
                <div className="font-mono text-xs text-neutral-500">{student.student_id}</div>
              </td>
              <td className="px-4 py-3">
                <div className="text-sm">{student.parent_name || student.parent_email || "-"}</div>
                {student.parent_email && student.parent_name && (
                  <div className="text-xs text-neutral-500">{student.parent_email}</div>
                )}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{student.active_session_count}</td>
              <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">
                {student.last_seen_at ? new Date(student.last_seen_at).toLocaleDateString() : "-"}
              </td>
              <td className="px-4 py-3">
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                  {student.status}
                </span>
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
