"use client";

import { useQuery } from "@tanstack/react-query";

import {
  getChildSchedule,
  listParentAttendance,
  listParentChildren,
  type ParentAttendanceRecord,
  type ParentChild,
  type ParentScheduleEntry,
} from "@/lib/api/parent";

const GRADIENTS = [
  "linear-gradient(135deg,#2563eb,#4f46e5)",
  "linear-gradient(135deg,#059669,#0d9488)",
  "linear-gradient(135deg,#d97706,#f59e0b)",
  "linear-gradient(135deg,#7c3aed,#db2777)",
  "linear-gradient(135deg,#0891b2,#2563eb)",
];
function nameGradient(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
  return GRADIENTS[Math.abs(h) % GRADIENTS.length];
}

export default function ParentChildrenPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  const { data: attendanceData } = useQuery({
    queryKey: ["parent", "attendance"],
    queryFn: listParentAttendance,
  });

  const children = data?.children ?? [];
  const allAttendance = attendanceData?.records ?? [];

  return (
    <section data-testid="parent-children">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
          My children
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
          Sessions, attendance &amp; progress
        </p>
      </div>

      {isError ? (
        <p className="text-sm" style={{ color: "#dc2626" }}>Could not load children.</p>
      ) : isLoading ? (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="rounded-2xl overflow-hidden" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
              <div className="h-24 shimmer" />
              <div className="p-4 space-y-2">
                <div className="h-3 w-32 rounded shimmer" />
                <div className="h-3 w-48 rounded shimmer" />
              </div>
            </div>
          ))}
        </div>
      ) : children.length === 0 ? (
        <div className="rounded-2xl p-8 text-center animate-fade-in-up" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
          <p className="text-sm" style={{ color: "var(--rally-muted)" }}>No children registered yet.</p>
        </div>
      ) : (
        <div className="space-y-4 stagger-children">
          {children.map((child) => (
            <ChildCard
              key={child.student_id}
              child={child}
              attendance={allAttendance.filter((r) => r.student_id === child.student_id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ChildCard({ child, attendance }: { child: ParentChild; attendance: ParentAttendanceRecord[] }) {
  const { data: scheduleData } = useQuery({
    queryKey: ["parent", "child-schedule", child.student_id],
    queryFn: () => getChildSchedule(child.student_id),
  });

  const sessions = scheduleData?.entries ?? [];
  const gradient = nameGradient(child.full_name);
  const presentCount = attendance.filter((r) => r.status === "present" || r.status === "late").length;
  const absentCount = attendance.filter((r) => r.status === "absent").length;

  return (
    <article
      className="rounded-2xl overflow-hidden animate-fade-in-up transition-all duration-200 hover:shadow-lg"
      style={{ background: "white", border: "1px solid var(--rally-line)" }}
    >
      {/* Gradient header */}
      <div className="px-4 py-4 flex items-center gap-3.5" style={{ background: gradient }}>
        <div
          className="h-12 w-12 rounded-xl flex items-center justify-center text-lg font-bold text-white shrink-0 shadow-lg"
          style={{ background: "rgba(255,255,255,0.2)", backdropFilter: "blur(4px)" }}
        >
          {child.full_name[0]}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-bold text-white text-[15px] tracking-tight truncate">{child.full_name}</h2>
          <span
            className="inline-block mt-1 text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ background: "rgba(255,255,255,0.2)", color: "white" }}
          >
            {child.status}
          </span>
        </div>
        <div className="flex gap-3 shrink-0 text-center">
          <div>
            <p className="font-bold text-white text-base leading-none">{presentCount}</p>
            <p className="text-white/60 text-[10px] mt-0.5">Present</p>
          </div>
          <div className="w-px self-stretch" style={{ background: "rgba(255,255,255,0.2)" }} />
          <div>
            <p className="font-bold text-white text-base leading-none">{absentCount}</p>
            <p className="text-white/60 text-[10px] mt-0.5">Absent</p>
          </div>
        </div>
      </div>

      {/* Sessions */}
      <div className="px-4 py-3 border-b" style={{ borderColor: "var(--rally-line)" }}>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: "var(--rally-cobalt)" }}>
          Upcoming sessions
        </p>
        {sessions.length === 0 ? (
          <p className="text-xs py-1" style={{ color: "var(--rally-subtle)" }}>No upcoming sessions.</p>
        ) : (
          <ul className="space-y-2">
            {sessions.map((s) => <SessionRow key={s.occurrence_id} entry={s} />)}
          </ul>
        )}
      </div>

      {/* Attendance log */}
      <div className="px-4 py-3">
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: "var(--rally-cobalt)" }}>
          Attendance log
        </p>
        {attendance.length === 0 ? (
          <p className="text-xs py-1" style={{ color: "var(--rally-subtle)" }}>No records yet.</p>
        ) : (
          <ul className="divide-y" style={{ borderColor: "var(--rally-line)" }}>
            {attendance.map((r) => <AttendanceRow key={r.attendance_id} record={r} />)}
          </ul>
        )}
      </div>
    </article>
  );
}

function SessionRow({ entry }: { entry: ParentScheduleEntry }) {
  const start = new Date(entry.start_at);
  const end = new Date(entry.end_at);
  const dateStr = start.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const timeStr = `${start.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })} – ${end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;

  return (
    <li className="flex gap-3 rounded-xl p-3" style={{ background: "var(--rally-cobalt-soft)" }}>
      <div
        className="h-9 w-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: "var(--rally-cobalt)" }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold truncate" style={{ color: "var(--rally-ink)" }}>{entry.session_title}</p>
        <p className="text-xs mt-0.5" style={{ color: "var(--rally-muted)" }}>{dateStr} · {timeStr}</p>
        {(entry.location || entry.coach_name) && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {entry.location && (
              <span className="text-[11px]" style={{ color: "var(--rally-muted)" }}>{entry.location}</span>
            )}
            {entry.coach_name && (
              <span
                className="text-[11px] font-semibold px-1.5 py-0.5 rounded"
                style={{ background: "rgba(37,99,235,0.1)", color: "var(--rally-cobalt)" }}
              >
                {entry.coach_name}
              </span>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function AttendanceRow({ record }: { record: ParentAttendanceRecord }) {
  const present = record.status === "present" || record.status === "late";
  return (
    <li className="flex items-center justify-between gap-3 py-2.5 text-xs">
      <div className="min-w-0 flex-1">
        <p className="font-semibold truncate" style={{ color: "var(--rally-ink)" }}>{record.session_title}</p>
        {record.coach_name && (
          <p className="mt-0.5" style={{ color: "var(--rally-muted)" }}>{record.coach_name}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span style={{ color: "var(--rally-subtle)" }}>{new Date(record.marked_at).toLocaleDateString()}</span>
        <span
          className="rounded-full px-2 py-0.5 font-bold text-[11px]"
          style={present ? { background: "#dcfce7", color: "#16a34a" } : { background: "#fee2e2", color: "#dc2626" }}
        >
          {record.status}
        </span>
      </div>
    </li>
  );
}
