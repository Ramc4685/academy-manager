import { useMemo, useRef, useState, useCallback } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import { api } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "../../components/ui/dialog";

export default function Calendar() {
  const { user } = useAuth();
  const calRef = useRef(null);
  const [selected, setSelected] = useState(null);

  const fetchEvents = useCallback(async (fetchInfo, success, failure) => {
    try {
      const { data } = await api.get("/calendar/events", {
        params: { start: fetchInfo.startStr.slice(0, 10), end: fetchInfo.endStr.slice(0, 10) },
      });
      success(data);
    } catch (e) {
      failure(e);
    }
  }, []);

  const initialView = useMemo(() => (window.innerWidth < 768 ? "timeGridDay" : "timeGridWeek"), []);

  const handleEventClick = (info) => {
    info.jsEvent.preventDefault();
    const e = info.event;
    setSelected({
      title: e.title,
      start: e.start,
      end: e.end,
      color: e.backgroundColor,
      ...e.extendedProps,
    });
  };

  return (
    <div className="space-y-6" data-testid="calendar-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl md:text-4xl font-display font-bold tracking-tighter text-slate-900">Calendar</h1>
          <p className="text-sm text-slate-600 mt-1">
            {user?.role === "parent"
              ? "Your child's upcoming sessions"
              : user?.role === "coach"
              ? "Your coaching schedule"
              : "Every active session across the academy"}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-emerald-500" /> Beginner</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-blue-600" /> Intermediate</span>
          <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-yellow-400" /> Advanced</span>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-3 md:p-5" data-testid="calendar-container">
        <FullCalendar
          ref={calRef}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView={initialView}
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridDay",
          }}
          height="auto"
          events={fetchEvents}
          eventClick={handleEventClick}
          allDaySlot={false}
          slotMinTime="06:00:00"
          slotMaxTime="22:00:00"
          nowIndicator
          firstDay={1}
        />
      </div>

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent data-testid="event-dialog">
          <DialogHeader>
            <DialogTitle className="font-display tracking-tight">{selected?.title}</DialogTitle>
            <DialogDescription>
              {selected?.start?.toLocaleString?.()} – {selected?.end?.toLocaleTimeString?.()}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-slate-500">Skill level</span><span className="font-medium capitalize">{selected.skill_level || "—"}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Coach</span><span className="font-medium">{selected.coach_name || "Unassigned"}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Location</span><span className="font-medium">{selected.location || "—"}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Capacity</span><span className="font-medium">{selected.max_students ?? "—"} students</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Monthly price</span><span className="font-medium">${selected.monthly_price ?? 0}</span></div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
