"use client";

import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";

import { getChildSchedule, listParentChildren } from "@/lib/api/parent";
import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import { Card } from "@/components/ds/card";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";

// FullCalendar (~250 KB) is loaded client-side only, out of the initial
// parent bundle — same pattern as AdminCalendarView.
const PersonaCalendarView = dynamic(
  () => import("@/components/calendar/PersonaCalendarView"),
  { ssr: false },
);

const CHILD_COLORS = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777"];

export default function ParentCalendarPage() {
  const {
    data: childrenData,
    isLoading: childrenLoading,
    isError: childrenError,
  } = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });

  const children = childrenData?.children ?? [];

  const scheduleQueries = useQueries({
    queries: children.map((child) => ({
      queryKey: ["parent", "child-schedule", child.student_id],
      queryFn: () => getChildSchedule(child.student_id),
      enabled: children.length > 0,
    })),
  });

  const isLoading = childrenLoading || scheduleQueries.some((q) => q.isLoading);
  const isError = childrenError || scheduleQueries.some((q) => q.isError);

  const scheduleSignature = scheduleQueries
    .map((q) => (q.data ? q.data.entries.map((e) => e.occurrence_id).join(",") : ""))
    .join("|");

  const events: CalendarViewEvent[] = useMemo(() => {
    const out: CalendarViewEvent[] = [];
    children.forEach((child, idx) => {
      const color = CHILD_COLORS[idx % CHILD_COLORS.length];
      const entries = scheduleQueries[idx]?.data?.entries ?? [];
      entries.forEach((e) => {
        out.push({
          id: e.occurrence_id,
          title: `${child.full_name} — ${e.session_title}`,
          start: e.start_at,
          end: e.end_at,
          color,
        });
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
      ) : (
        <PersonaCalendarView events={events} />
      )}
    </section>
  );
}
