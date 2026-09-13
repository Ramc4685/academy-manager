"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQueries, useQuery } from "@tanstack/react-query";

import { getCoachToday, type CoachSession } from "@/lib/api/coach";
import {
  coachSessionHref,
  isCancelled,
  markProgress,
  recentUnmarkedSessions,
} from "@/lib/coach/marking";
import { queryKeys } from "@/lib/query/keys";
import { reportVitals } from "@/lib/pwa/vitals";
import { formatSessionTimeRange, sessionDateKey } from "@/lib/time/session-time";

function todayISO(offset = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export default function CoachTodayPage() {
  const [date, setDate] = useState<string>(() => todayISO());

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });
  const sessions = useMemo(
    () => (Array.isArray(data?.sessions) ? data.sessions : []),
    [data],
  );

  // "Recent, not fully marked" (#777) is relative to NOW, so it is only shown
  // while the coach is looking at today. The two preceding days cover the 48h
  // window; the filter below drops anything older.
  const viewingToday = date === todayISO();
  const lookbackDates = useMemo(
    () => (viewingToday ? [todayISO(-1), todayISO(-2)] : []),
    [viewingToday],
  );
  const lookbackQueries = useQueries({
    queries: lookbackDates.map((d) => ({
      queryKey: queryKeys.coach.today(d),
      queryFn: () => getCoachToday(d),
      staleTime: 5 * 60 * 1000,
    })),
  });
  const lookbackSessions = lookbackQueries.flatMap((q) => q.data?.sessions ?? []);
  // Only PREVIOUS days: today's own classes already carry a "Needs marks"
  // badge in the list below, and repeating them here would be noise.
  const recentUnmarked: CoachSession[] = recentUnmarkedSessions(lookbackSessions);

  useMemo(() => reportVitals("coach.today"), []);

  return (
    <section data-testid="coach-today">
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Today</h1>
          <p className="text-sm text-neutral-500">{date}</p>
        </div>
        <DatePicker date={date} onChange={setDate} />
      </header>

      {isLoading && <SessionSkeleton />}

      {isError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Couldn&apos;t load today.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border px-3"
          >
            Retry
          </button>
        </div>
      )}

      {!isError && data && sessions.length === 0 && (
        <p className="text-neutral-500" data-testid="empty-state">
          No sessions today.
        </p>
      )}

      {recentUnmarked.length > 0 && (
        <section className="mb-4" data-testid="recent-unmarked">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Recent, not fully marked
          </h2>
          <ul className="space-y-2">
            {recentUnmarked.map((s) => (
              <li key={`recent-${s.occurrence_id}`}>
                <Link
                  href={
                    coachSessionHref(
                      s.occurrence_id,
                      sessionDateKey(s.start_at, s.timezone),
                    ) as Parameters<typeof Link>[0]["href"]
                  }
                  data-testid={`recent-unmarked-${s.occurrence_id}`}
                  className="block rounded-lg border border-amber-300 bg-amber-50 p-3 hover:border-amber-500 dark:border-amber-900 dark:bg-amber-950"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="min-w-0 truncate font-semibold">{s.title}</p>
                    <span className="shrink-0 text-sm tabular-nums text-amber-900 dark:text-amber-200">
                      {markProgress(s.roster).label}
                    </span>
                  </div>
                  <p className="text-sm text-neutral-600 dark:text-neutral-300">
                    {sessionDateKey(s.start_at, s.timezone)} ·{" "}
                    {formatSessionTimeRange(s.start_at, s.end_at, s.timezone)}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ul className="space-y-3" data-testid="session-list">
        {sessions.map((s) => {
          const cancelled = isCancelled(s);
          const progress = markProgress(s.roster);
          return (
          <li key={s.occurrence_id} className="space-y-2">
            <Link
              href={
                coachSessionHref(s.occurrence_id, date) as Parameters<
                  typeof Link
                >[0]["href"]
              }
              className="block rounded-lg border border-neutral-200 bg-white p-3 hover:border-blue-400 dark:border-neutral-800 dark:bg-neutral-900"
              data-testid={`session-${s.session_id}`}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className={`font-semibold ${cancelled ? "line-through" : ""}`}>
                    {s.title}
                  </p>
                  <p className="text-sm text-neutral-500">{s.location}</p>
                  {s.coach_name && (
                    <p className="text-sm text-neutral-500" data-testid="session-coach-name">
                      Coach: {s.coach_name}
                    </p>
                  )}
                </div>
                <p
                  className={`shrink-0 text-sm tabular-nums text-neutral-600 dark:text-neutral-300 ${
                    cancelled ? "line-through" : ""
                  }`}
                >
                  {formatSessionTimeRange(s.start_at, s.end_at, s.timezone)}
                </p>
              </div>
              {cancelled ? (
                <p
                  className="mt-2 text-sm font-semibold text-red-700 dark:text-red-300"
                  data-testid={`session-cancelled-${s.occurrence_id}`}
                >
                  Cancelled
                  {s.cancellation_reason ? ` · ${s.cancellation_reason}` : ""}
                </p>
              ) : (
                <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-neutral-500">
                  <span data-testid={`session-marked-${s.occurrence_id}`}>
                    {progress.label}
                  </span>
                  {!progress.complete && (
                    <span
                      data-testid={`needs-marks-${s.occurrence_id}`}
                      className="rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
                    >
                      Needs marks
                    </span>
                  )}
                </p>
              )}
            </Link>
            {!cancelled && (
              <Link
                href={
                  `/coach/today/plan?date=${date}` as Parameters<
                    typeof Link
                  >[0]["href"]
                }
                data-testid={`view-teaching-plan-${s.session_id}`}
                className="block min-h-touch rounded-lg border border-rally-base/30 px-4 py-2 text-center text-sm font-semibold text-rally-base hover:bg-rally-base/5"
              >
                View teaching plan
              </Link>
            )}
          </li>
          );
        })}
      </ul>

      {isFetching && !isLoading && (
        <p className="mt-3 text-xs text-neutral-400">Refreshing…</p>
      )}
    </section>
  );
}

function DatePicker({
  date,
  onChange,
}: {
  date: string;
  onChange: (d: string) => void;
}) {
  const shift = (days: number) => {
    const [year, month, day] = date.split("-").map(Number);
    const d = new Date(year, month - 1, day);
    d.setDate(d.getDate() + days);
    const nextYear = d.getFullYear();
    const nextMonth = String(d.getMonth() + 1).padStart(2, "0");
    const nextDay = String(d.getDate()).padStart(2, "0");
    onChange(`${nextYear}-${nextMonth}-${nextDay}`);
  };
  return (
    <div className="flex items-center gap-1">
      <button
        aria-label="Previous day"
        onClick={() => shift(-1)}
        className="min-h-touch min-w-touch rounded-md border border-neutral-300 px-2 dark:border-neutral-700"
      >
        ‹
      </button>
      <button
        onClick={() => onChange(todayISO())}
        className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700"
      >
        Today
      </button>
      <button
        aria-label="Next day"
        onClick={() => shift(1)}
        className="min-h-touch min-w-touch rounded-md border border-neutral-300 px-2 dark:border-neutral-700"
      >
        ›
      </button>
    </div>
  );
}

function SessionSkeleton() {
  return (
    <ul className="space-y-3">
      {[0, 1].map((i) => (
        <li
          key={i}
          className="h-24 animate-pulse rounded-lg border border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900"
        />
      ))}
    </ul>
  );
}
