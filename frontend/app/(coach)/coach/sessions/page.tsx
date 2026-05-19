"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCoachToday } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function CoachSessionsPage() {
  const date = todayISO();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.coach.today(date),
    queryFn: () => getCoachToday(date),
    staleTime: 5 * 60 * 1000,
  });
  const sessions = Array.isArray(data?.sessions) ? data.sessions : [];

  return (
    <section data-testid="coach-sessions">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <p className="text-sm text-neutral-500">{date}</p>
      </header>

      {isLoading && <p className="text-neutral-500">Loading sessions...</p>}

      {isError && (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>Couldn&apos;t load sessions.</p>
          <button
            onClick={() => void refetch()}
            className="mt-2 min-h-touch rounded-md border border-red-200 px-3 dark:border-red-800"
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && sessions.length === 0 && (
        <p className="text-neutral-500">No sessions today.</p>
      )}

      <ul className="space-y-3">
        {sessions.map((session) => (
          <li key={session.session_id}>
            <Link
              href={`/coach/sessions/${session.session_id}` as Parameters<typeof Link>[0]["href"]}
              className="block rounded-lg border border-neutral-200 bg-white p-4 hover:border-blue-400 dark:border-neutral-800 dark:bg-neutral-900"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-semibold">{session.title}</p>
                  <p className="text-sm text-neutral-500">{session.location}</p>
                </div>
                <p className="text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
                  {formatTimeRange(session.start_at, session.end_at)}
                </p>
              </div>
              <p className="mt-2 text-sm text-neutral-500">
                {session.roster.length} {session.roster.length === 1 ? "student" : "students"}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatTimeRange(start: string, end: string): string {
  const fmt = (value: string) =>
    new Date(value).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  return `${fmt(start)} - ${fmt(end)}`;
}
