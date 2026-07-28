"use client";

import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { getMySchedule } from "@/lib/api/student";
import { queryKeys } from "@/lib/query/keys";

export default function StudentSchedulePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.student.schedule(),
    queryFn: getMySchedule,
  });

  const entries = data?.entries ?? [];

  return (
    <section data-testid="student-schedule">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Schedule</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Your upcoming sessions</p>
      </div>

      {isError ? (
        <p className="text-sm text-status-red-600">Could not load your schedule.</p>
      ) : isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} variant="line" height="3.5rem" />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="rounded-2xl p-10 bg-white border border-rally-line">
          <EmptyState title="No upcoming sessions" description="Your sessions will appear here once scheduled" />
        </div>
      ) : (
        <ul className="space-y-2 stagger-children">
          {entries.map((entry) => (
            <li
              key={entry.occurrence_id}
              className="rounded-2xl p-4 bg-white border border-rally-line animate-fade-in-up"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-bold truncate text-rally-ink">{entry.session_title}</p>
                  <p className="text-xs mt-0.5 text-rally-muted">
                    {new Date(entry.start_at).toLocaleString(undefined, {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </p>
                  {entry.location && (
                    <p className="text-xs mt-0.5 text-rally-subtle">{entry.location}</p>
                  )}
                  {entry.coach_name && (
                    <p className="text-xs mt-0.5 text-rally-subtle">Coach {entry.coach_name}</p>
                  )}
                </div>
                <span className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-rally-cobalt-50 text-rally-cobalt-600">
                  {entry.status}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
