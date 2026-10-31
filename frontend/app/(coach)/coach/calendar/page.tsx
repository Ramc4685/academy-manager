"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";

import { getCoachSchedule } from "@/lib/api/coach";
import { coachScheduleToCalendar } from "@/lib/coach/schedule-links";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";
import { RetryButton } from "@/components/coach/RetryButton";
import { CalendarTimeZoneUnavailable } from "@/components/calendar/CalendarTimeZoneUnavailable";

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

  // #1043: the grid runs on the session/academy zone every coach detail
  // screen formats in. Issue #777: each event links to its occurrence on the
  // class's LOCAL date — a session-id link with no date landed on "Session
  // not found."
  const { events, timeZone } = useMemo(
    () => coachScheduleToCalendar(data?.sessions ?? []),
    [data],
  );

  return (
    <section data-testid="coach-calendar" className="space-y-4">
      <h1 className="text-lg font-semibold text-rally-ink">Calendar</h1>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">Failed to load your schedule.</p>
            <RetryButton onClick={() => void refetch()} />
          </div>
        </Card>
      )}

      {isLoading ? (
        <Card p={16}>
          <Skeleton variant="block" height={280} />
        </Card>
      ) : isError && !data ? null : timeZone.status === "ready" ? (
        <PersonaCalendarView events={events} timeZone={timeZone.timeZone} />
      ) : events.length === 0 ? (
        <Card p={16}>
          <p className="text-sm text-rally-muted">No upcoming sessions.</p>
        </Card>
      ) : (
        <CalendarTimeZoneUnavailable listHref="/coach/sessions" listLabel="Sessions" />
      )}
    </section>
  );
}
