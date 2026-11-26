import type { AdminToday, AdminTodayClass } from "@/lib/api/admin";
import type { ChipVariant } from "@/components/ds/chip";
import { formatAcademyDay, formatInAcademyZone } from "@/lib/format/academy-time";

const CLOCK: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" };

/** "4:30 PM – 5:30 PM", on the academy clock. */
export function classTimeRange(cls: Pick<AdminTodayClass, "start_at" | "end_at">, timezone: string | null) {
  const start = formatInAcademyZone(cls.start_at, timezone, CLOCK);
  const end = formatInAcademyZone(cls.end_at, timezone, CLOCK);
  return end ? `${start} – ${end}` : start;
}

export function classClock(iso: string, timezone: string | null): string {
  return formatInAcademyZone(iso, timezone, CLOCK);
}

/** "Thu, Nov 26" for the academy's calendar date (a YYYY-MM-DD string). */
export function todayDateLabel(date: string): string {
  return formatAcademyDay(`${date}T00:00:00Z`, "UTC", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function phaseChip(cls: Pick<AdminTodayClass, "phase" | "starts_in_minutes">): {
  variant: ChipVariant;
  label: string;
} {
  switch (cls.phase) {
    case "now":
      return { variant: "present", label: "NOW" };
    case "next":
      return {
        variant: "pending",
        label: cls.starts_in_minutes != null ? `NEXT · in ${cls.starts_in_minutes} min` : "NEXT",
      };
    case "finished":
      return { variant: "expired", label: "FINISHED" };
    case "cancelled":
      return { variant: "failed", label: "CANCELLED" };
    default:
      return { variant: "draft", label: "LATER" };
  }
}

/** "11 enrolled · 9 here · 1 absent", or "· not marked yet" before any mark. */
export function countLine(
  cls: Pick<AdminTodayClass, "enrolled_count" | "here_count" | "absent_count" | "marked_count">,
): string {
  if (cls.marked_count === 0) return `${cls.enrolled_count} enrolled · not marked yet`;
  return `${cls.enrolled_count} enrolled · ${cls.here_count} here · ${cls.absent_count} absent`;
}

export function healthNotesLabel(count: number): string {
  return `${count} health ${count === 1 ? "note" : "notes"}`;
}

/**
 * Fills a partial payload (an e2e catch-all stub answers `{}`) with empty
 * defaults, so the block renders "No classes today" rather than crashing.
 */
export function normalizeToday(raw: AdminToday | undefined, fallbackDate: string): AdminToday | undefined {
  if (!raw) return undefined;
  return {
    ...raw,
    date: raw.date ?? fallbackDate,
    timezone: raw.timezone ?? "",
    classes: Array.isArray(raw.classes) ? raw.classes : [],
    tomorrow: raw.tomorrow ?? { class_count: 0, first_start_at: null },
    health_enabled: raw.health_enabled ?? false,
  };
}

/** The live class a quick action defaults to: the one on now, else the next one. */
export function liveClass(classes: AdminTodayClass[]): AdminTodayClass | undefined {
  return classes.find((c) => c.phase === "now") ?? classes.find((c) => c.phase === "next");
}

export const HOW_LATE_MAX = 40;

/** 8.3: exactly this and nothing else about the child goes to the coach. */
export function runningLateMessage(
  childName: string,
  cls: Pick<AdminTodayClass, "title" | "start_at">,
  timezone: string | null,
  howLate: string,
): string {
  const base = `${childName} is running late for ${cls.title} (${classClock(cls.start_at, timezone)}).`;
  const extra = howLate.trim().slice(0, HOW_LATE_MAX);
  return extra ? `${base} ${extra}` : base;
}
