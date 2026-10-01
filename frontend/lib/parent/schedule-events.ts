import type { CalendarViewEvent } from "@/components/calendar/PersonaCalendarView";
import type { ParentScheduleEntry } from "@/lib/api/parent";

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

export function scheduleEntryToEvent(
  entry: ParentScheduleEntry,
  { childName, color }: { childName: string; color: string },
): CalendarViewEvent {
  const cancelled = entry.status === "cancelled";
  const sourceLabel = scheduleSourceLabel(entry.source);
  const base = `${childName} — ${entry.session_title}`;
  const labelled = sourceLabel ? `${sourceLabel} — ${base}` : base;
  return {
    id: entry.occurrence_id,
    title: cancelled ? `Cancelled — ${labelled}` : labelled,
    start: entry.start_at,
    end: entry.end_at,
    color: cancelled ? CANCELLED_EVENT_COLOR : color,
  };
}
