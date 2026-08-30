"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";

import { getCoachSchedule } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";

// FullCalendar (~250 KB) is loaded client-side only, out of the initial
// coach bundle — same pattern as AdminCalendarView.
const PersonaCalendarView = dynamic(
  () => import("@/components/calendar/PersonaCalendarView"),
  { ssr: false },
);

export default function CoachCalendarPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.coach.calendar(),
    queryFn: getCoachSchedule,
  });

  const sessions = data?.sessions ?? [];

  const events: CalendarViewEvent[] = useMemo(
    () =>
      (data?.sessions ?? []).map((s) => ({
        id: s.occurrence_id,
        title: s.title,
        start: s.start_at,
        end: s.end_at,
        url: `/coach/sessions/${encodeURIComponent(s.session_id)}`,
      })),
    [data],
  );

  return (
    <section data-testid="coach-calendar" className="space-y-4">
      <h1 className="text-lg font-semibold text-rally-ink">Calendar</h1>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load your schedule.</p>
            <button onClick={() => void refetch()} className="text-sm font-medium text-rally-cobalt">
              Retry
            </button>
          </div>
        </Card>
      )}

      {isLoading ? (
        <Card p={16}>
          <Skeleton variant="block" height={280} />
        </Card>
      ) : (
        <PersonaCalendarView events={events} />
      )}
    </section>
  );
}
