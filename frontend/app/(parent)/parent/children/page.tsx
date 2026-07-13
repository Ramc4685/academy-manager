"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { queryKeys } from "@/lib/query/keys";
import {
  getCancellationPreview,
  getChildSchedule,
  getParentAcademy,
  listParentAttendance,
  listParentChildren,
  listParentEnrollments,
  selfCancelEnrollment,
  submitAbsenceNotice,
  type ParentAttendanceRecord,
  type ParentChild,
  type ParentEnrollment,
  type ParentScheduleEntry,
} from "@/lib/api/parent";
import { formatAcademyDate, formatAcademyTimeRange } from "@/lib/format/academy-time";

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

function money(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
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
  const { data: academy } = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const { data: enrollmentsData } = useQuery({
    queryKey: ["parent", "enrollments"],
    queryFn: listParentEnrollments,
  });

  const children = data?.children ?? [];
  const allAttendance = attendanceData?.records ?? [];
  const allEnrollments = enrollmentsData?.enrollments ?? [];
  const academyTimezone = academy?.timezone ?? null;

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
              enrollments={allEnrollments.filter((e) => e.student_id === child.student_id)}
              academyTimezone={academyTimezone}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ChildCard({
  child,
  attendance,
  enrollments,
  academyTimezone,
}: {
  child: ParentChild;
  attendance: ParentAttendanceRecord[];
  enrollments: ParentEnrollment[];
  academyTimezone: string | null;
}) {
  const { data: scheduleData } = useQuery({
    queryKey: ["parent", "child-schedule", child.student_id],
    queryFn: () => getChildSchedule(child.student_id),
  });

  const sessions = scheduleData?.entries ?? [];
  const gradient = nameGradient(child.full_name);
  const presentCount = attendance.filter((r) => r.status === "present" || r.status === "late").length;
  const absentCount = attendance.filter((r) => r.status === "absent").length;
  const activeEnrollments = enrollments.filter((e) => e.status === "active");

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
            {sessions.map((s) => (
              <SessionRow key={s.occurrence_id} studentId={child.student_id} entry={s} academyTimezone={academyTimezone} />
            ))}
          </ul>
        )}
      </div>

      {/* Enrollments */}
      {activeEnrollments.length > 0 && (
        <div className="px-4 py-3 border-b" style={{ borderColor: "var(--rally-line)" }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: "var(--rally-cobalt)" }}>
            Enrollments
          </p>
          <ul className="space-y-2">
            {activeEnrollments.map((e) => (
              <EnrollmentRow key={e.enrollment_id} enrollment={e} />
            ))}
          </ul>
        </div>
      )}

      {/* Attendance log */}
      <div className="px-4 py-3">
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: "var(--rally-cobalt)" }}>
          Attendance log
        </p>
        {attendance.length === 0 ? (
          <p className="text-xs py-1" style={{ color: "var(--rally-subtle)" }}>No records yet.</p>
        ) : (
          <ul className="divide-y" style={{ borderColor: "var(--rally-line)" }}>
            {attendance.map((r) => (
              <AttendanceRow key={r.attendance_id} record={r} academyTimezone={academyTimezone} />
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function SessionRow({
  studentId,
  entry,
  academyTimezone,
}: {
  studentId: string;
  entry: ParentScheduleEntry;
  academyTimezone: string | null;
}) {
  const queryClient = useQueryClient();
  const [submitted, setSubmitted] = useState(false);
  const whenStr = formatAcademyTimeRange(entry.start_at, entry.end_at, academyTimezone);

  const absenceMutation = useMutation({
    mutationFn: submitAbsenceNotice,
    onSuccess: () => {
      setSubmitted(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.parent.absences() });
    },
  });

  return (
    <li className="flex flex-col gap-2 rounded-xl p-3" style={{ background: "var(--rally-cobalt-soft)" }}>
      <div className="flex gap-3">
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
          <p className="text-xs mt-0.5" style={{ color: "var(--rally-muted)" }}>{whenStr}</p>
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
      </div>

      {absenceMutation.isError && (
        <p role="alert" className="text-xs" style={{ color: "#dc2626" }}>
          {absenceMutation.error instanceof Error ? absenceMutation.error.message : "Could not report absence."}
        </p>
      )}

      {submitted ? (
        <p role="status" className="text-xs font-semibold" style={{ color: "#16a34a" }}>
          Absence reported
        </p>
      ) : (
        <Button
          variant="secondary"
          size="sm"
          disabled={absenceMutation.isPending}
          onClick={() =>
            absenceMutation.mutate({ student_id: studentId, occurrence_id: entry.occurrence_id })
          }
        >
          {absenceMutation.isPending ? "Reporting…" : "Report absence"}
        </Button>
      )}
    </li>
  );
}

function EnrollmentRow({ enrollment }: { enrollment: ParentEnrollment }) {
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="rounded-xl p-3" style={{ background: "var(--rally-paper)" }}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold truncate" style={{ color: "var(--rally-ink)" }}>{enrollment.session_title}</p>
          <p className="text-xs mt-0.5" style={{ color: "var(--rally-muted)" }}>Active enrollment</p>
        </div>
        <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>
          Cancel enrollment…
        </Button>
      </div>
      {confirming && (
        <CancelEnrollmentDialog enrollment={enrollment} onClose={() => setConfirming(false)} />
      )}
    </li>
  );
}

function CancelEnrollmentDialog({
  enrollment,
  onClose,
}: {
  enrollment: ParentEnrollment;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<{ status: string; fee_cents: number } | null>(null);

  const previewQuery = useQuery({
    queryKey: queryKeys.parent.cancellationPreview(enrollment.enrollment_id),
    queryFn: () => getCancellationPreview(enrollment.enrollment_id),
  });

  const cancelMutation = useMutation({
    mutationFn: () => selfCancelEnrollment(enrollment.enrollment_id, { reason }),
    onSuccess: (res) => {
      setResult({ status: res.status, fee_cents: res.fee_cents });
      void queryClient.invalidateQueries({ queryKey: ["parent", "enrollments"] });
    },
  });

  const preview = previewQuery.data;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Cancel enrollment in ${enrollment.session_title}`}
      className="mt-3 rounded-xl border p-3"
      style={{ borderColor: "#fecaca", background: "#fff5f5" }}
    >
      {result ? (
        <div className="space-y-3">
          <p role="status" className="text-sm font-semibold" style={{ color: "var(--rally-ink)" }}>
            Enrollment {result.status}
            {result.fee_cents > 0 ? ` — fee charged: ${money(result.fee_cents)}` : " — no fee charged"}
          </p>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      ) : previewQuery.isError ? (
        <div className="space-y-3">
          <p role="alert" className="text-sm" style={{ color: "#991b1b" }}>
            Could not load cancellation details.
          </p>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      ) : previewQuery.isLoading ? (
        <div className="space-y-2">
          <div className="h-4 w-40 rounded shimmer" />
          <div className="h-4 w-56 rounded shimmer" />
        </div>
      ) : preview ? (
        <div className="space-y-3">
          <div className="text-sm" style={{ color: "var(--rally-ink)" }}>
            <p className="font-semibold">Cancellation fee: {money(preview.fee_cents)}</p>
            <p className="mt-1 text-xs" style={{ color: "var(--rally-muted)" }}>
              Effective timing: {preview.effective_timing}
            </p>
            <p className="mt-1 text-xs" style={{ color: "var(--rally-muted)" }}>
              {preview.notice_met ? "Notice period met" : "Notice period not met"}
            </p>
            {!preview.allowed && preview.blocked_reason && (
              <p role="alert" className="mt-2 text-xs font-semibold" style={{ color: "#991b1b" }}>
                {preview.blocked_reason}
              </p>
            )}
          </div>

          {preview.allowed && (
            <>
              <label className="block text-xs font-semibold" style={{ color: "var(--rally-muted)" }}>
                Reason
                <textarea
                  className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
                  style={{ borderColor: "var(--rally-line)" }}
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why are you cancelling?"
                />
              </label>

              {cancelMutation.isError && (
                <p role="alert" className="text-xs" style={{ color: "#991b1b" }}>
                  {cancelMutation.error instanceof Error ? cancelMutation.error.message : "Could not cancel enrollment."}
                </p>
              )}

              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={onClose} disabled={cancelMutation.isPending}>
                  Keep enrollment
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!reason.trim() || cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate()}
                >
                  {cancelMutation.isPending ? "Cancelling…" : "Confirm cancellation"}
                </Button>
              </div>
            </>
          )}

          {!preview.allowed && (
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function AttendanceRow({
  record,
  academyTimezone,
}: {
  record: ParentAttendanceRecord;
  academyTimezone: string | null;
}) {
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
        <span style={{ color: "var(--rally-subtle)" }}>{formatAcademyDate(record.marked_at, academyTimezone)}</span>
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
