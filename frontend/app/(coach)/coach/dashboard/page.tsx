"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCoachDashboard, getCoachToday } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";


function todayISO(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function CoachDashboardPage() {
  const date = todayISO();
  const { data } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });
  const metricsQuery = useQuery({
    queryKey: queryKeys.coach.dashboard(),
    queryFn: getCoachDashboard,
    staleTime: 5 * 60 * 1000,
  });

  const sessions = data?.sessions ?? [];
  const studentCount = sessions.reduce(
    (sum, session) => sum + session.roster.length,
    0,
  );

  return (
    <section data-testid="coach-dashboard">
      <header className="mb-5">
        <h1 className="font-display text-2xl font-semibold tracking-tight">
          Coach dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Your assigned sessions and roster for today.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3">
        <Metric
          label="Sessions today"
          value={
            metricsQuery.isLoading
              ? "-"
              : String(metricsQuery.data?.sessions_today ?? sessions.length)
          }
        />
        <Metric
          label="Students coached"
          value={
            metricsQuery.isLoading
              ? "-"
              : String(metricsQuery.data?.active_student_count ?? studentCount)
          }
        />
        <Metric
          label="Attendance rate"
          value={
            metricsQuery.isLoading
              ? "-"
              : `${metricsQuery.data?.attendance_percentage ?? 0}%`
          }
        />
        <Metric
          label="Expected cut"
          value={
            metricsQuery.isLoading
              ? "-"
              : money(metricsQuery.data?.expected_cut_cents ?? 0)
          }
        />
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Today</h2>
          <Link
            href="/coach/today"
            className="text-sm font-medium text-blue-600 hover:underline"
          >
            Open today
          </Link>
        </div>
        {sessions.length === 0 ? (
          <p className="text-sm text-slate-500">No sessions today.</p>
        ) : (
          <ul className="space-y-2">
            {sessions.slice(0, 4).map((session) => (
              <li key={session.occurrence_id}>
                <Link
                  href={
                    // Use raw UTC date to match backend _day_bounds_utc.
                    `/coach/sessions/${encodeURIComponent(session.occurrence_id)}?date=${session.start_at.slice(0, 10)}` as Parameters<
                      typeof Link
                    >[0]["href"]
                  }
                  className="block rounded-md border border-slate-100 p-3 hover:border-blue-300 dark:border-slate-800"
                >
                  <p className="font-medium">{session.title}</p>
                  <p className="text-xs text-slate-500">{session.location}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function money(cents: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
  }).format(cents / 100);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-500">
        {label}
      </p>
      <p className="mt-2 font-display text-3xl font-semibold text-slate-950 dark:text-white">
        {value}
      </p>
    </div>
  );
}
