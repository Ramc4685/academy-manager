import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";

/**
 * Coach daily-operations screen (Phase 5 Slice 7).
 *
 * Mobile-first: card-per-session and card-per-student, tap targets >= 44px.
 * Manual refresh only — no auto-polling. Payment info is intentionally
 * hidden on this surface.
 */
export default function CoachToday() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get("/coach/today")
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    // Intentionally no polling, no interval. Manual refresh only.
  }, [load]);

  return (
    <div className="space-y-6 px-4 sm:px-6" data-testid="coach-today">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tight text-slate-900">
            Today
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            {data?.date ? data.date : "Loading..."}
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          data-testid="coach-today-refresh"
          className="min-h-[44px] min-w-[44px] px-4 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 hover:bg-slate-50 active:bg-slate-100"
        >
          Refresh
        </button>
      </div>

      {loading && !data && (
        <div className="text-sm text-slate-500" data-testid="coach-today-loading">
          Loading...
        </div>
      )}
      {error && (
        <div
          className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-3"
          data-testid="coach-today-error"
        >
          {error}
        </div>
      )}

      {data && data.sessions && data.sessions.length === 0 && (
        <div
          className="rounded-xl border border-slate-200 bg-white p-6 text-center"
          data-testid="coach-today-empty"
        >
          <div className="text-base font-medium text-slate-700">No sessions today</div>
          <div className="text-sm text-slate-500 mt-1">Enjoy your day off.</div>
        </div>
      )}

      <div className="space-y-4">
        {(data?.sessions || []).map((s) => (
          <SessionCard key={s.id} session={s} />
        ))}
      </div>
    </div>
  );
}


function SessionCard({ session }) {
  return (
    <section
      className="rounded-xl border border-slate-200 bg-white shadow-sm"
      data-testid={`session-card-${session.id}`}
    >
      <header className="p-4 border-b border-slate-100">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-display font-semibold text-slate-900 text-lg leading-tight">
              {session.name}
            </h2>
            <div className="text-xs text-slate-500 mt-1">
              {session.start_time}
              {session.end_time ? `–${session.end_time}` : ""}
            </div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2">
          <Link
            to={session.shortcuts?.attendance_path || "#"}
            className="min-h-[44px] flex items-center justify-center rounded-lg bg-blue-600 text-white text-sm font-semibold px-3 hover:bg-blue-700 active:bg-blue-800"
            data-testid={`session-${session.id}-attendance`}
          >
            Mark Attendance
          </Link>
          <Link
            to={session.shortcuts?.lesson_plan_path || "#"}
            className="min-h-[44px] flex items-center justify-center rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50"
            data-testid={`session-${session.id}-lesson-plan`}
          >
            Lesson Plan
          </Link>
          <Link
            to={session.shortcuts?.progress_note_path || "#"}
            className="min-h-[44px] flex items-center justify-center rounded-lg border border-slate-200 text-sm font-medium text-slate-700 hover:bg-slate-50"
            data-testid={`session-${session.id}-progress`}
          >
            Progress Notes
          </Link>
        </div>
      </header>

      <ul className="divide-y divide-slate-100" data-testid={`session-${session.id}-roster`}>
        {(session.roster || []).length === 0 && (
          <li className="p-4 text-sm text-slate-500">No students enrolled.</li>
        )}
        {(session.roster || []).map((row) => (
          <RosterRow key={row.student_id} row={row} />
        ))}
      </ul>
    </section>
  );
}


function RosterRow({ row }) {
  return (
    <li
      className="p-4 flex items-center justify-between gap-3 min-h-[56px]"
      data-testid={`roster-row-${row.student_id}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <div className="font-medium text-slate-900 truncate">{row.name}</div>
        {row.has_medical_notes && (
          <span
            title="Has medical notes"
            aria-label="Has medical notes"
            data-testid={`roster-${row.student_id}-medical`}
            className="inline-flex items-center justify-center rounded-full bg-amber-100 text-amber-800 text-xs font-semibold w-6 h-6"
          >
            M
          </span>
        )}
        {row.is_paused && (
          <span
            title="Enrollment paused"
            aria-label="Paused"
            data-testid={`roster-${row.student_id}-paused`}
            className="inline-flex items-center justify-center rounded-full bg-slate-200 text-slate-700 text-xs font-semibold w-6 h-6"
          >
            P
          </span>
        )}
      </div>
      <AttendancePill status={row.attendance_status} />
    </li>
  );
}


function AttendancePill({ status }) {
  const map = {
    present: { label: "Present", cls: "bg-emerald-100 text-emerald-800" },
    absent: { label: "Absent", cls: "bg-red-100 text-red-800" },
    late: { label: "Late", cls: "bg-amber-100 text-amber-800" },
    excused: { label: "Excused", cls: "bg-slate-100 text-slate-700" },
    make_up: { label: "Make-up", cls: "bg-blue-100 text-blue-800" },
  };
  const entry = status && map[status];
  const label = entry ? entry.label : "Pending";
  const cls = entry ? entry.cls : "bg-slate-50 text-slate-500 border border-slate-200";
  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${cls}`}
      data-testid="attendance-pill"
    >
      {label}
    </span>
  );
}
