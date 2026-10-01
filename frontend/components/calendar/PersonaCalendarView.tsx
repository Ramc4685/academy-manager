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
import luxonPlugin from "@fullcalendar/luxon3";

import { calendarTimeZoneLabel } from "@/lib/time/calendar-timezone";
import { useIsPhone } from "@/lib/use-is-phone";

import styles from "./persona-calendar-view.module.css";

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
  /**
   * #1043: the IANA zone the grid runs on — the academy/session zone the
   * detail screens use. Required: FullCalendar's default is the browser
   * zone, which showed a 6:00 PM Chicago class as "4p" in Los Angeles.
   * Callers resolve it with `resolveCalendarTimeZone` and render their own
   * explicit state when no valid zone is known.
   */
  timeZone: string;
  onEventClick?: (event: CalendarViewEvent) => void;
}

export default function PersonaCalendarView({ events, timeZone, onEventClick }: Props) {
  const byId = new Map(events.map((e) => [e.id, e]));
  /**
   * #896: a month grid on a 400px phone is 7 columns of ~50px — the coach
   * and parent calendars were unreadable and untappable one-handed. Below
   * the `md:` breakpoint the calendar opens on a single day instead, with
   * the month still one tap away in the toolbar.
   *
   * The day view comes from the daygrid plugin the component already loads,
   * so it adds no view plugin of its own.
   */
  const phone = useIsPhone();

  return (
    <div
      data-testid="calendar-grid"
      className={`${styles.wrap} rounded-lg border border-rally-line bg-white p-4`}
    >
      <p
        data-testid="calendar-timezone"
        className="mb-3 text-xs text-rally-subtle"
      >
        {calendarTimeZoneLabel(timeZone)}
      </p>
      <FullCalendar
        // `initialView` is read once at mount, so crossing the breakpoint has
        // to remount rather than re-render. The events prop is unchanged.
        key={`${phone ? "phone" : "wide"}:${timeZone}`}
        // The luxon plugin is FullCalendar's named-zone implementation; without
        // it a named `timeZone` silently degrades to UTC.
        plugins={[dayGridPlugin, luxonPlugin]}
        // Day placement, event times and the Today button all follow this
        // zone (DST included), not the viewer's browser clock.
        timeZone={timeZone}
        initialView={phone ? "dayGridDay" : "dayGridMonth"}
        events={events}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: phone ? "dayGridDay,dayGridMonth" : "dayGridMonth,dayGridWeek",
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
