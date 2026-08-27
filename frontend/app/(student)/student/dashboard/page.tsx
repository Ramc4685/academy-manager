"use client";

import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { getMyProfile, getMySchedule } from "@/lib/api/student";
import { queryKeys } from "@/lib/query/keys";

export default function StudentDashboardPage() {
  const profileQuery = useQuery({
    queryKey: queryKeys.student.me(),
    queryFn: getMyProfile,
  });
  const scheduleQuery = useQuery({
    queryKey: queryKeys.student.schedule(),
    queryFn: getMySchedule,
  });

  const nextEntries = (scheduleQuery.data?.entries ?? []).slice(0, 3);

  return (
    <section data-testid="student-dashboard">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">
          {profileQuery.data ? `Hi, ${profileQuery.data.full_name.split(" ")[0]}` : "Dashboard"}
        </h1>
        <p className="text-sm mt-0.5 text-rally-muted">
          {profileQuery.data?.academy_name ?? "Your schedule and progress"}
        </p>
      </div>

      {/* Level summary */}
      {profileQuery.isLoading ? (
        <div className="h-20 animate-pulse rounded-2xl shimmer mb-4" />
      ) : (
        <div className="rounded-2xl p-4 bg-white border border-rally-line mb-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-rally-subtle">
            Current level
          </p>
          <p className="mt-1 text-lg font-bold text-rally-ink">
            {profileQuery.data?.level ?? "Not placed yet"}
          </p>
        </div>
      )}

      {/* Next sessions */}
      <div>
        <h2 className="font-display text-lg font-bold tracking-tight text-rally-ink mb-2">
          Next sessions
        </h2>
        {scheduleQuery.isLoading ? (
          <div className="space-y-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} variant="line" height="3.5rem" />
            ))}
          </div>
        ) : nextEntries.length === 0 ? (
          <div className="rounded-2xl p-8 bg-white border border-rally-line">
            <EmptyState title="No upcoming sessions" description="Check back once your schedule is set" />
          </div>
        ) : (
          <ul className="space-y-2 stagger-children">
            {nextEntries.map((entry) => (
              <li
                key={entry.occurrence_id}
                className="rounded-2xl p-4 bg-white border border-rally-line animate-fade-in-up"
              >
                <p className="text-sm font-bold text-rally-ink">{entry.session_title}</p>
                <p className="text-xs mt-0.5 text-rally-muted">
                  {new Date(entry.start_at).toLocaleString(undefined, {
                    weekday: "short",
                    month: "short",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                  {entry.location ? ` · ${entry.location}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
