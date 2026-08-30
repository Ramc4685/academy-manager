"use client";

/**
 * PersonaCalendarView — shared FullCalendar month/week grid (UIM13).
 *
 * Persona-agnostic: coach/parent pages adapt their own data (coach
 * sessions, parent per-child schedules) into `CalendarViewEvent[]` and
 * pass them in. Mirrors `frontend/components/admin/AdminCalendarView.tsx`
 * — only this file imports from `@fullcalendar/*`, and callers must
 * `dynamic(() => import(...), { ssr: false })` to keep FullCalendar
 * (~250 KB) out of the initial persona bundle.
 */

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";

export interface CalendarViewEvent {
  id: string;
  title: string;
  start: string;
  end?: string;
  /** Navigate here on click, e.g. a session detail route. */
  url?: string;
  /** Per-series color (e.g. one color per parent child). */
  color?: string;
}

interface Props {
  events: CalendarViewEvent[];
  onEventClick?: (event: CalendarViewEvent) => void;
}

export default function PersonaCalendarView({ events, onEventClick }: Props) {
  const byId = new Map(events.map((e) => [e.id, e]));

  return (
    <div
      data-testid="calendar-grid"
      className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4"
    >
      <FullCalendar
        plugins={[dayGridPlugin]}
        initialView="dayGridMonth"
        events={events}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,dayGridWeek",
        }}
        height="auto"
        eventClick={(info) => {
          info.jsEvent.preventDefault();
          const event = byId.get(info.event.id);
          if (!event) return;
          if (onEventClick) {
            onEventClick(event);
          } else if (event.url && event.url.startsWith("/") && !event.url.startsWith("//")) {
            // Same-origin paths only. This component is persona-agnostic and
            // a future caller may pass a server-supplied url through; without
            // this guard that would be an open redirect (or a `javascript:`
            // XSS sink). Today's callers build fixed, encoded paths.
            window.location.href = event.url;
          }
        }}
      />
    </div>
  );
}
