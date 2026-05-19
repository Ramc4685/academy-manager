"use client";

/**
 * AdminCalendarView — FullCalendar view of sessions.
 *
 * Only this file imports from @fullcalendar/*. The sessions page uses:
 *   dynamic(() => import("@/components/admin/AdminCalendarView"), { ssr: false })
 *
 * This keeps FullCalendar (~250 KB) out of the initial sessions bundle.
 */

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import type { AdminSessionView } from "@/lib/api/admin";

interface Props {
  sessions: AdminSessionView[];
}

export default function AdminCalendarView({ sessions }: Props) {
  const events = sessions.map((s) => ({
    id: s.session_id,
    title: `${s.title} (${s.enrolled_count}/${s.capacity})`,
    start: s.start_at,
    end: s.end_at,
    url: `/admin/sessions/${s.session_id}`,
  }));

  return (
    <div className="rounded-lg border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-4">
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
          // Navigate to session detail instead of opening popover
          info.jsEvent.preventDefault();
          if (info.event.url) {
            window.location.href = info.event.url;
          }
        }}
      />
    </div>
  );
}
