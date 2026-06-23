"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { getCoachSchedule, type CoachScheduleEntry } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { formatSessionTimeRange, sessionDateKey } from "@/lib/time/session-time";

export default function CoachSessionsPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.coach.schedule(),
    queryFn: getCoachSchedule,
    staleTime: 5 * 60 * 1000,
  });

  const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
  const grouped = groupByDate(sessions);

  return (
    <section data-testid="coach-sessions">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <p className="text-sm text-neutral-500">Your upcoming schedule</p>
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
        <p className="text-neutral-500">No upcoming sessions.</p>
      )}

      <div className="space-y-6">
        {grouped.map(({ label, sessions: daySessions }) => (
          <div key={label}>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
              {label}
            </h2>
            <ul className="space-y-3">
              {daySessions.map((session) => (
                <li key={session.occurrence_id}>
                  <Link
                    href={
                      // Raw UTC date matches backend _day_bounds_utc; sessionDateKey
                      // is only for grouping headers (evening sessions cross UTC midnight).
                      `/coach/sessions/${encodeURIComponent(session.occurrence_id)}?date=${session.start_at.slice(0, 10)}` as Parameters<
                        typeof Link
                      >[0]["href"]
                    }
                    className="block rounded-lg border border-neutral-200 bg-white p-3 hover:border-blue-400 dark:border-neutral-800 dark:bg-neutral-900"
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <p className="font-semibold">{session.title}</p>
                        <p className="text-sm text-neutral-500">
                          {session.location}
                        </p>
                      </div>
                      <p className="shrink-0 text-sm tabular-nums text-neutral-600 dark:text-neutral-300">
                        {formatSessionTimeRange(session.start_at, session.end_at, session.timezone)}
                      </p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatDateLabel(key: string): string {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

function groupByDate(
  sessions: CoachScheduleEntry[],
): { label: string; sessions: CoachScheduleEntry[] }[] {
  const map = new Map<string, CoachScheduleEntry[]>();
  for (const s of sessions) {
    const key = sessionDateKey(s.start_at, s.timezone);
    const bucket = map.get(key) ?? [];
    bucket.push(s);
    map.set(key, bucket);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, items]) => ({ label: formatDateLabel(key), sessions: items }));
}
