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

export function scheduleEntryToEvent(
  entry: ParentScheduleEntry,
  { childName, color }: { childName: string; color: string },
): CalendarViewEvent {
  const cancelled = entry.status === "cancelled";
  return {
    id: entry.occurrence_id,
    title: cancelled
      ? `Cancelled — ${childName} — ${entry.session_title}`
      : `${childName} — ${entry.session_title}`,
    start: entry.start_at,
    end: entry.end_at,
    color: cancelled ? CANCELLED_EVENT_COLOR : color,
  };
}
