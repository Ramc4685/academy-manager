import type { AdminSessionOccurrenceView } from "@/lib/api/admin";
import { formatAcademyDate } from "@/lib/format/academy-time";
import { sessionDateKey } from "@/lib/time/session-time";

export interface MonthDateClass {
  occurrence: AdminSessionOccurrenceView;
  sessionTitle: string;
}

export interface MonthDate {
  /** "YYYY-MM-DD" in the academy timezone. */
  day: string;
  classes: MonthDateClass[];
}

/** Every date in `month` that has at least one class, oldest first. */
export function groupMonthDates(
  classes: MonthDateClass[],
  month: string,
  timeZone: string,
): MonthDate[] {
  const days = new Map<string, MonthDateClass[]>();
  for (const c of classes) {
    const day = sessionDateKey(c.occurrence.start_at, timeZone);
    if (!day.startsWith(month)) continue;
    days.set(day, [...(days.get(day) ?? []), c]);
  }
  return [...days.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, list]) => ({
      day,
      classes: list.sort((a, b) => a.occurrence.start_at.localeCompare(b.occurrence.start_at)),
    }));
}

/** A live date can still be called off; a cancelled or finished one cannot. */
export function isEditable(o: AdminSessionOccurrenceView, now: Date): boolean {
  return o.status === "scheduled" && new Date(o.start_at).getTime() > now.getTime();
}

/** Occurrence ids the admin unticked that are still live: the ones to cancel. */
export function datesToCancel(
  dates: MonthDate[],
  noClass: ReadonlySet<string>,
  now: Date,
): string[] {
  return dates
    .flatMap((d) => d.classes)
    .filter((c) => noClass.has(c.occurrence.occurrence_id) && isEditable(c.occurrence, now))
    .map((c) => c.occurrence.occurrence_id);
}

const MAX_ANNOUNCEMENT = 2000;

/**
 * One class's schedule for the month, as the announcement families get.
 * Returns null when the class has no dates that month.
 */
export function scheduleAnnouncement(
  sessionTitle: string,
  occurrences: AdminSessionOccurrenceView[],
  monthLabel: string,
  timeZone: string,
): string | null {
  if (occurrences.length === 0) return null;
  const sorted = [...occurrences].sort((a, b) => a.start_at.localeCompare(b.start_at));
  const on = sorted.filter((o) => o.status !== "cancelled");
  const off = sorted.filter((o) => o.status === "cancelled");
  const line = (o: AdminSessionOccurrenceView) =>
    `- ${formatAcademyDate(o.start_at, timeZone)}${
      o.status === "cancelled" && o.cancellation_reason ? ` (${o.cancellation_reason})` : ""
    }`;
  const parts = [`${sessionTitle}: ${monthLabel} schedule is final.`];
  parts.push(on.length ? `Class:\n${on.map(line).join("\n")}` : "No classes this month.");
  if (off.length) parts.push(`No class:\n${off.map(line).join("\n")}`);
  parts.push("Your calendar in the parent portal shows the same dates.");
  return parts.join("\n\n").slice(0, MAX_ANNOUNCEMENT);
}
