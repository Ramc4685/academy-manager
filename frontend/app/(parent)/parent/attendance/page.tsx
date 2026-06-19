"use client";

import { useQuery } from "@tanstack/react-query";

import { listParentAttendance } from "@/lib/api/parent";

function statusPill(status: string): { bg: string; color: string } {
  switch (status) {
    case "present":
    case "attended":
      return { bg: "#e1f5ee", color: "#0f6e56" };
    case "absent":
      return { bg: "#fcebeb", color: "#a32d2d" };
    case "late":
    case "excused":
      return { bg: "#faeeda", color: "#854f0b" };
    default:
      return { bg: "#f1efe8", color: "#5f5e5a" };
  }
}

export default function ParentAttendancePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "attendance"],
    queryFn: listParentAttendance,
  });

  const records = data?.records ?? [];

  return (
    <section data-testid="parent-attendance">
      <div className="mb-4 animate-fade-in-up">
        <h1
          className="font-display text-2xl font-bold tracking-tight"
          style={{ color: "var(--rally-ink)" }}
        >
          Attendance
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
          Class check-ins
        </p>
      </div>

      {isError ? (
        <p className="text-sm" style={{ color: "#dc2626" }}>
          Could not load attendance.
        </p>
      ) : isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-2xl overflow-hidden"
              style={{ background: "white", border: "1px solid var(--rally-line)" }}
            >
              <div className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="space-y-2 flex-1">
                    <div className="h-3 w-32 rounded shimmer" />
                    <div className="h-3 w-48 rounded shimmer" />
                  </div>
                  <div className="h-5 w-16 rounded-full shimmer" />
                </div>
                <div className="h-3 w-24 rounded shimmer mt-2" />
              </div>
            </div>
          ))}
        </div>
      ) : records.length === 0 ? (
        <div
          className="rounded-2xl p-8 text-center animate-fade-in-up"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <p className="text-sm" style={{ color: "var(--rally-muted)" }}>
            No attendance recorded yet.
          </p>
        </div>
      ) : (
        <ul className="space-y-3 stagger-children">
          {records.map((record) => {
            const pill = statusPill(record.status);
            return (
              <li
                key={record.attendance_id}
                className="rounded-2xl animate-fade-in-up"
                style={{ background: "white", border: "1px solid var(--rally-line)" }}
              >
                <div className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p
                        className="font-semibold text-sm truncate"
                        style={{ color: "var(--rally-ink)" }}
                      >
                        {record.student_name}
                      </p>
                      <p
                        className="text-sm mt-0.5 truncate"
                        style={{ color: "var(--rally-muted)" }}
                      >
                        {record.session_title}
                      </p>
                    </div>
                    <span
                      className="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize"
                      style={{ background: pill.bg, color: pill.color }}
                    >
                      {record.status}
                    </span>
                  </div>
                  <p
                    className="mt-2 text-xs"
                    style={{ color: "var(--rally-muted)" }}
                  >
                    {new Date(record.marked_at).toLocaleString()}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
