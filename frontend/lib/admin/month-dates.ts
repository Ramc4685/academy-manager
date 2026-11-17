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

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const DATE_TOKEN =
  /\b(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})\/(\d{1,2})(?:\/\d{2,4})?|(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?)\b/gi;
const RANGE_GAP = /^\s*(?:-|–|—|to|through|thru)\s*$/i;

/**
 * The non-AI fallback: days of `month` ("YYYY-MM") written in `text` as
 * "Dec 22", "December 22nd", "12/22" or "2026-12-22", plus spans joined by
 * "-", "to" or "through" ("Dec 21 - Jan 2", "Dec 21-24"). Returns "YYYY-MM-DD"s.
 */
export function plainDatesInMonth(text: string, month: string): Set<string> {
  const year = Number(month.slice(0, 4));
  const tokens: { day: string; start: number; end: number }[] = [];
  const target = Number(month.slice(5, 7));
  for (const m of text.matchAll(DATE_TOKEN)) {
    let y = year;
    let mo: number;
    let d: number;
    if (m[1]) [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    else if (m[4]) [mo, d] = [Number(m[4]), Number(m[5])];
    else {
      [mo, d] = [MONTHS.indexOf(m[6].slice(0, 3).toLowerCase()) + 1, Number(m[7])];
    }
    if (mo < 1 || mo > 12 || d < 1 || d > 31) continue;
    // No year written: the year that puts the date nearest the month ("Dec 21 - Jan 2").
    if (!m[1] && Math.abs(mo - target) > 6) y = mo > target ? year - 1 : year + 1;
    tokens.push({ day: isoDay(y, mo, d), start: m.index, end: m.index + m[0].length });
  }
  // "Dec 21-24": a bare day number right after a dash continues the month.
  for (const m of text.matchAll(/(\d{1,2})(?:st|nd|rd|th)?\s*[-–]\s*(\d{1,2})\b(?!\/)/g)) {
    const owner = tokens.find((t) => t.end === m.index + m[1].length);
    const d = Number(m[2]);
    if (!owner || d < 1 || d > 31 || tokens.some((t) => t.start === m.index + m[0].length - m[2].length)) continue;
    const [y, mo] = owner.day.split("-").map(Number);
    tokens.push({ day: isoDay(y, mo, d), start: m.index + m[0].length - m[2].length, end: m.index + m[0].length });
  }
  tokens.sort((a, b) => a.start - b.start);
  const days = new Set<string>();
  tokens.forEach((t, i) => {
    days.add(t.day);
    const next = tokens[i + 1];
    if (next && RANGE_GAP.test(text.slice(t.end, next.start)) && next.day > t.day) {
      for (let d = addDay(t.day); d < next.day; d = addDay(d)) days.add(d);
    }
  });
  return new Set([...days].filter((d) => d.startsWith(month)));
}

function isoDay(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function addDay(day: string): string {
  const t = new Date(`${day}T12:00:00Z`);
  t.setUTCDate(t.getUTCDate() + 1);
  return t.toISOString().slice(0, 10);
}

/** composition/admin.py `_series_occurrence_candidates`: recurring dates exist 60 days ahead. */
export const SCHEDULE_HORIZON_DAYS = 60;

/**
 * The academy-local day from which every date of `month` exists, or null when
 * it already does. Before then a recurring class's later dates aren't on the
 * schedule, so the month can't be reviewed or published as final.
 */
export function monthCompleteFrom(month: string, now: Date, timeZone: string): string | null {
  const [y, m] = month.split("-").map(Number);
  const lastDay = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
  const horizon = sessionDateKey(new Date(now.getTime() + SCHEDULE_HORIZON_DAYS * 86_400_000).toISOString(), timeZone);
  if (lastDay <= horizon) return null;
  const from = new Date(`${lastDay}T12:00:00Z`);
  from.setUTCDate(from.getUTCDate() - SCHEDULE_HORIZON_DAYS);
  return from.toISOString().slice(0, 10);
}
