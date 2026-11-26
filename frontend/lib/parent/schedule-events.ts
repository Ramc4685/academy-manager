import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import type { ParentScheduleEntry } from "@/lib/api/parent";
import { calendarInstant } from "@/lib/time/calendar-timezone";

/**
 * Grey used for a class the academy called off (#671).
 *
 * `GetChildSchedule` reads `list_for_session_between`, which — unlike every
 * coach-facing read — has no `status != "cancelled"` filter, so a cancelled
 * date still reaches the parent calendar. Drawn in the child's normal colour
 * it contradicts the cancellation email the family just received, and they
 * bring their child to a closed gym.
 */
export const CANCELLED_EVENT_COLOR = "#9ca3af";

/**
 * Badge text for a one-time class (#1038): an approved make-up or trial is
 * on the schedule alongside regular classes and must be told apart from
 * them. `null` for a regular class (or a payload without `source`).
 */
export function scheduleSourceLabel(source: string | null | undefined): "Make-up" | "Trial" | null {
  if (source === "makeup") return "Make-up";
  if (source === "trial") return "Trial";
  return null;
}

/** The parent-facing reason a date has no class. */
export function noClassReason(entry: Pick<ParentScheduleEntry, "cancellation_reason">): string {
  const reason = entry.cancellation_reason?.trim();
  // A whole-session cancel stamps a machine code, not a sentence.
  return !reason || reason === "session_cancelled" ? "Class cancelled" : reason;
}

/** A date that already carries an absence notice: shown, never offered again. */
export const ALREADY_REPORTED_LABEL = "Already reported";

/**
 * S18: late marks count as present by design (the BFF counts present + late),
 * so the label says so rather than the count changing.
 */
export const PRESENT_INCLUDING_LATE = "Present (including late)";

export function presentIncludingLate(records: ReadonlyArray<{ status: string }>): number {
  return records.filter((r) => r.status === "present" || r.status === "late").length;
}

/** S17: the chip a reported absence wears on Home and Calendar. */
export const ABSENT_REPORTED_CHIP = "Absent (reported)";

/**
 * Whether the academy has published `month` ("YYYY-MM") as final. An academy
 * that never publishes (`publishedThrough` null) shows every month as final,
 * which is how the calendar behaved before publishing existed.
 */
export function isMonthPublished(month: string, publishedThrough: string | null | undefined): boolean {
  return !publishedThrough || month <= publishedThrough;
}

export function scheduleEntryToEvent(
  entry: ParentScheduleEntry,
  { childName, color }: { childName: string; color: string },
): CalendarViewEvent {
  const cancelled = entry.status === "cancelled";
  const sourceLabel = scheduleSourceLabel(entry.source);
  const base = `${childName} — ${entry.session_title}`;
  const sourced = sourceLabel ? `${sourceLabel} — ${base}` : base;
  const labelled = entry.absence_reported ? `${ABSENT_REPORTED_CHIP} — ${sourced}` : sourced;
  return {
    id: entry.occurrence_id,
    title: cancelled ? `No class (${noClassReason(entry)}) — ${labelled}` : labelled,
    // #1043: explicit UTC instants, so the academy-zone grid cannot read a
    // naive timestamp as wall time in its own zone.
    start: calendarInstant(entry.start_at),
    end: calendarInstant(entry.end_at),
    color: cancelled ? CANCELLED_EVENT_COLOR : color,
  };
}
