"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCoachToday } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { reportVitals } from "@/lib/pwa/vitals";

function todayISO(offset = 0): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

export default function CoachTodayPage() {
  const [date, setDate] = useState<string>(() => todayISO());

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });

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
        <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <p>Couldn't load today.</p>
          <button onClick={() => void refetch()} className="mt-2 min-h-touch rounded-md border px-3">
            Retry
          </button>
        </div>
      )}

      {data && data.sessions.length === 0 && (
        <p className="text-neutral-500" data-testid="empty-state">No sessions today.</p>
      )}

      <ul className="space-y-3" data-testid="session-list">
        {data?.sessions.map((s) => (
          <li key={s.session_id}>
            <Link
              href={`/coach/sessions/${s.session_id}` as Parameters<typeof Link>[0]["href"]}
              className="block rounded-lg border border-neutral-200 bg-white p-4 hover:border-blue-400 dark:border-neutral-800 dark:bg-neutral-900"
              data-testid={`session-${s.session_id}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-semibold">{s.title}</p>
                  <p className="text-sm text-neutral-500">{s.location}</p>
                </div>
                <p className="text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
                  {formatTimeRange(s.start_at, s.end_at)}
                </p>
              </div>
              <p className="mt-2 text-sm text-neutral-500">
                {s.roster.length} {s.roster.length === 1 ? "student" : "students"}
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

function DatePicker({ date, onChange }: { date: string; onChange: (d: string) => void }) {
  const shift = (days: number) => {
    const d = new Date(`${date}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + days);
    onChange(d.toISOString().slice(0, 10));
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

function formatTimeRange(start: string, end: string): string {
  const fmt = (s: string) =>
    new Date(s).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${fmt(start)} – ${fmt(end)}`;
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
