"use client";

import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";

import { getChildSchedule, getParentAcademy, listParentChildren } from "@/lib/api/parent";
import { scheduleEntryToEvent } from "@/lib/parent/schedule-events";
import { queryKeys } from "@/lib/query/keys";
import { resolveCalendarTimeZone } from "@/lib/time/calendar-timezone";
import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { CalendarTimeZoneUnavailable } from "@/components/calendar/CalendarTimeZoneUnavailable";

// FullCalendar (~250 KB) is loaded client-side only, out of the initial
// parent bundle — same pattern as AdminCalendarView.
const PersonaCalendarView = dynamic(
  () => import("@/components/calendar/PersonaCalendarView"),
  { ssr: false },
);

// #843: same Rally-only rotation as the avatar gradients, so a child keeps a
// system colour here too (purple/pink had no token behind them).
const CHILD_COLORS = ["#2563eb", "#059669", "#d97706", "#475569", "#0891b2"];

export default function ParentCalendarPage() {
  const {
    data: childrenData,
    isLoading: childrenLoading,
    isError: childrenError,
  } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });

  // #1043: the grid runs on the academy's clock — the same zone the My
  // children and Requests screens format class times in — never the
  // browser's. Same query key as those screens, so it is usually cached.
  const academyQuery = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  const calendarZone = resolveCalendarTimeZone([academyQuery.data?.timezone]);

  const children = childrenData?.children ?? [];

  const scheduleQueries = useQueries({
    queries: children.map((child) => ({
      queryKey: ["parent", "child-schedule", child.student_id],
      queryFn: () => getChildSchedule(child.student_id),
      enabled: children.length > 0,
    })),
  });

  const isLoading =
    childrenLoading || academyQuery.isLoading || scheduleQueries.some((q) => q.isLoading);
  const isError = childrenError || scheduleQueries.some((q) => q.isError);

  const scheduleSignature = scheduleQueries
    .map((q) =>
      q.data ? q.data.entries.map((e) => `${e.occurrence_id}:${e.status}`).join(",") : "",
    )
    .join("|");

  const events: CalendarViewEvent[] = useMemo(() => {
    const out: CalendarViewEvent[] = [];
    children.forEach((child, idx) => {
      const color = CHILD_COLORS[idx % CHILD_COLORS.length];
      const entries = scheduleQueries[idx]?.data?.entries ?? [];
      // Cancelled dates come back from this feed too (#671); the mapper
      // greys them out rather than letting them read as a normal class.
      entries.forEach((e) => {
        out.push(scheduleEntryToEvent(e, { childName: child.full_name, color }));
      });
    });
    return out;
    // scheduleQueries' array identity changes every render; key off a stable
    // signature of the underlying data instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [children, scheduleSignature]);

  return (
    <section data-testid="parent-calendar" className="space-y-4">
      <h1 className="text-lg font-semibold text-rally-ink">Calendar</h1>

      {isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <p role="alert" className="text-sm text-red-800">
            Failed to load one or more schedules.
          </p>
        </Card>
      )}

      {academyQuery.isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" className="flex items-center justify-between gap-3">
            <p className="text-sm text-red-800">
              Couldn&apos;t load the academy&apos;s timezone, so the calendar can&apos;t be shown.
            </p>
            <Button type="button" variant="secondary" onClick={() => void academyQuery.refetch()}>
              Retry
            </Button>
          </div>
        </Card>
      )}

      {children.length > 0 && (
        <div className="flex flex-wrap gap-3" data-testid="calendar-child-legend">
          {children.map((child, idx) => (
            <span key={child.student_id} className="flex items-center gap-1.5 text-xs text-rally-subtle">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: CHILD_COLORS[idx % CHILD_COLORS.length] }}
              />
              {child.full_name}
            </span>
          ))}
        </div>
      )}

      {isLoading ? (
        <Card p={16}>
          <Skeleton variant="block" height={280} />
        </Card>
      ) : children.length === 0 ? (
        <Card p={16}>
          <EmptyState title="No children on file" description="Add a child to see their schedule here." />
        </Card>
      ) : calendarZone.status === "ready" ? (
        <PersonaCalendarView events={events} timeZone={calendarZone.timeZone} />
      ) : academyQuery.isError ? null : (
        <CalendarTimeZoneUnavailable listHref="/parent/children" listLabel="My children" />
      )}
    </section>
  );
}
