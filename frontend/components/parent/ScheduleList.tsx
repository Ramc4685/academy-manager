"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { Card } from "@/components/ds/card";
import type { ParentScheduleEntry } from "@/lib/api/parent";
import { formatAcademyTimeRange, monthLabel } from "@/lib/format/academy-time";
import { isMonthPublished, noClassReason } from "@/lib/parent/schedule-events";
import { sessionDateKey } from "@/lib/time/session-time";

export interface ScheduleListRow {
  entry: ParentScheduleEntry;
  childName: string;
}

interface Props {
  rows: ScheduleListRow[];
  timeZone: string;
  publishedThrough: string | null | undefined;
  now?: Date;
  /** `?occurrence=` from a cancellation push: that date is scrolled to and outlined. */
  highlightOccurrenceId?: string | null;
}

/**
 * The phone-first schedule: every upcoming date, grouped by month, each one
 * plainly "Class" or "No class" with the academy's reason. A month the
 * academy has not published yet says so, so nobody plans around a tentative
 * date as if it were final.
 */
export function ScheduleList({
  rows,
  timeZone,
  publishedThrough,
  now = new Date(),
  highlightOccurrenceId = null,
}: Props) {
  const upcoming = rows
    .filter((row) => new Date(row.entry.end_at).getTime() >= now.getTime())
    .sort((a, b) => a.entry.start_at.localeCompare(b.entry.start_at));
  // Rows are this family's own schedule, so another family's or a past date
  // matches nothing and the note below says so instead of a dead end.
  const highlightMissing =
    Boolean(highlightOccurrenceId) &&
    !upcoming.some((row) => row.entry.occurrence_id === highlightOccurrenceId);
  const missingNote = highlightMissing ? (
    <Card p={12}>
      <p data-testid="schedule-occurrence-missing" role="status" className="text-sm text-rally-muted">
        That class date isn&apos;t among the upcoming dates shown here. It may have passed or be further out.
      </p>
    </Card>
  ) : null;

  if (upcoming.length === 0) {
    return (
      <div className="space-y-4">
        {missingNote}
        <Card p={16}>
          <p className="text-sm text-rally-subtle">No upcoming classes on the schedule yet.</p>
        </Card>
      </div>
    );
  }

  const months = new Map<string, ScheduleListRow[]>();
  for (const row of upcoming) {
    const month = sessionDateKey(row.entry.start_at, timeZone).slice(0, 7);
    months.set(month, [...(months.get(month) ?? []), row]);
  }

  return (
    <div className="space-y-4" data-testid="parent-schedule-list">
      {missingNote}
      {[...months.entries()].map(([month, monthRows]) => {
        const published = isMonthPublished(month, publishedThrough);
        return (
          <Card key={month} p={16}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-rally-ink">{monthLabel(month)}</h2>
              {publishedThrough && published && (
                <span className="rounded px-2 py-0.5 text-xs font-semibold bg-status-green-50 text-status-green-800">
                  Confirmed
                </span>
              )}
            </div>
            {!published && (
              <p
                role="note"
                data-testid="schedule-month-unconfirmed"
                className="mt-2 rounded px-3 py-2 text-xs bg-status-amber-50 text-status-amber-800"
              >
                These dates aren&apos;t confirmed yet. The academy will publish the final schedule.
              </p>
            )}
            <ul className={`mt-2 divide-y divide-rally-line ${published ? "" : "opacity-70"}`}>
              {monthRows.map(({ entry, childName }) => {
                const cancelled = entry.status === "cancelled";
                return (
                  <ScheduleRow
                    key={`${entry.occurrence_id}:${childName}`}
                    highlighted={entry.occurrence_id === highlightOccurrenceId}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-rally-ink">
                        {formatAcademyTimeRange(entry.start_at, entry.end_at, timeZone)}
                      </p>
                      <p className="text-xs text-rally-subtle">
                        {childName} · {entry.session_title}
                        {entry.location ? ` · ${entry.location}` : ""}
                      </p>
                      {cancelled && (
                        <p className="mt-0.5 text-xs font-semibold text-status-red-800">
                          {noClassReason(entry)}
                        </p>
                      )}
                    </div>
                    <span
                      className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${
                        cancelled
                          ? "bg-status-red-50 text-status-red-800"
                          : "bg-status-green-50 text-status-green-800"
                      }`}
                    >
                      {cancelled ? "No class" : "Class"}
                    </span>
                  </ScheduleRow>
                );
              })}
            </ul>
          </Card>
        );
      })}
    </div>
  );
}

function ScheduleRow({
  highlighted,
  children,
}: {
  highlighted: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (highlighted) ref.current?.scrollIntoView({ block: "center" });
  }, [highlighted]);
  return (
    <li
      ref={ref}
      className={`flex items-start justify-between gap-3 py-2.5${
        highlighted ? " -mx-2 rounded px-2 ring-2 ring-rally-cobalt-600" : ""
      }`}
      data-testid="schedule-row"
      data-highlighted={highlighted || undefined}
    >
      {children}
    </li>
  );
}
