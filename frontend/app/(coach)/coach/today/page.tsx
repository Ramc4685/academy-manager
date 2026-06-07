"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCoachToday } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { reportVitals } from "@/lib/pwa/vitals";
import { formatSessionTimeRange } from "@/lib/time/session-time";

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
  const sessions = Array.isArray(data?.sessions) ? data.sessions : [];

  useMemo(() => reportVitals("coach.today"), []);

  return (
    <section data-testid="coach-today">
      <header className="mb-4 flex items-center justify-between">
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

      <ul className="space-y-3" data-testid="session-list">
        {sessions.map((s) => (
          <li key={s.occurrence_id}>
            <Link
              href={
                `/coach/sessions/${encodeURIComponent(s.occurrence_id)}?date=${date}` as Parameters<
                  typeof Link
                >[0]["href"]
              }
              className="block rounded-lg border border-neutral-200 bg-white p-4 hover:border-blue-400 dark:border-neutral-800 dark:bg-neutral-900"
              data-testid={`session-${s.session_id}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold">{s.title}</p>
                  <p className="text-sm text-neutral-500">{s.location}</p>
                </div>
                <p className="text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
                  {formatSessionTimeRange(s.start_at, s.end_at, s.timezone)}
                </p>
              </div>
              <p className="mt-2 text-sm text-neutral-500">
                {s.roster.length}{" "}
                {s.roster.length === 1 ? "student" : "students"}
              </p>
            </Link>
          </li>
        ))}
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
