"use client";

import { useQuery } from "@tanstack/react-query";

import { listParentAttendance } from "@/lib/api/parent";

export default function ParentAttendancePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "attendance"],
    queryFn: listParentAttendance,
  });

  const records = data?.records ?? [];

  return (
    <section data-testid="parent-attendance">
      <h1 className="mb-4 text-2xl font-semibold">Attendance</h1>
      {isError ? (
        <p className="text-sm text-red-600">Could not load attendance.</p>
      ) : isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : records.length === 0 ? (
        <p className="text-sm text-neutral-500">No attendance recorded yet.</p>
      ) : (
        <ul className="space-y-3">
          {records.map((record) => (
            <li key={record.attendance_id} className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-medium">{record.student_name}</p>
                  <p className="text-sm text-neutral-500">{record.session_title}</p>
                </div>
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium capitalize text-blue-700">
                  {record.status}
                </span>
              </div>
              <p className="mt-2 text-xs text-neutral-500">{new Date(record.marked_at).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
