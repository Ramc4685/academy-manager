import { readFileSync } from "node:fs";
import { join } from "node:path";
import { formatDate } from "@fullcalendar/core";
import luxonPlugin from "@fullcalendar/luxon3";
import { describe, expect, it } from "vitest";

import type { CoachScheduleEntry } from "@/lib/api/coach";
import type { ParentScheduleEntry as ParentEntry } from "@/lib/api/parent";
import { coachScheduleToCalendar } from "@/lib/coach/schedule-links";
import { scheduleEntryToEvent } from "@/lib/parent/schedule-events";
import { resolveCalendarTimeZone } from "@/lib/time/calendar-timezone";

/**
 * #1043 — the coach and parent calendars placed classes on the BROWSER's
 * clock: a 6:00 PM Chicago class read "4p" in Los Angeles, and near midnight
 * it could land on another day.
 *
 * There is no DOM in this suite, so these tests drive FullCalendar's own
 * date environment (`formatDate` builds the same `DateEnv` the grid uses)
 * with the exact named-zone implementation `PersonaCalendarView` loads.
 * Day placement, event time and "today" all come from that environment.
 *
 * Run under several browser zones to prove the result does not depend on
 * the viewer's clock, e.g.
 *   TZ=America/Los_Angeles pnpm vitest run components/calendar
 *   TZ=Pacific/Kiritimati  pnpm vitest run components/calendar
 */

/** What the grid shows for an instant: its day cell and its wall time. */
function onGrid(instant: string, timeZone: string): string {
  return formatDate(instant, {
    timeZone,
    // Same named-zone implementation the component registers via plugins.
    namedTimeZoneImpl: (luxonPlugin as unknown as { namedTimeZonedImpl: unknown })
      .namedTimeZonedImpl,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  } as Parameters<typeof formatDate>[1]);
}

function coachEntry(start_at: string, end_at: string, timezone: string): CoachScheduleEntry {
  return {
    session_id: "sess-1",
    occurrence_id: "occ-1",
    title: "Juniors 6:00 PM",
    location: "Court 1",
    timezone,
    start_at,
    end_at,
  };
}

function parentEntry(start_at: string, end_at: string, status = "scheduled"): ParentEntry {
  return {
    occurrence_id: "occ-1",
    session_id: "sess-1",
    session_title: "Juniors 6:00 PM",
    location: "Court 1",
    start_at,
    end_at,
    status,
    coach_name: null,
  };
}

/**
 * One fixture, both personas. `grid` is "MM/DD/YYYY, HH:mm" in the academy
 * zone — the date the event sits on and the time printed on it.
 */
const FIXTURES: Array<{
  name: string;
  zone: string;
  start: string;
  end: string;
  grid: string;
  date: string;
}> = [
  {
    name: "Chicago 6:00 PM CDT (the live report)",
    zone: "America/Chicago",
    start: "2026-10-01T23:00:00Z",
    end: "2026-10-02T00:00:00Z",
    grid: "10/01/2026, 18:00",
    date: "2026-10-01",
  },
  {
    name: "Chicago 6:45 PM CDT crossing UTC midnight",
    zone: "America/Chicago",
    start: "2026-10-01T23:45:00Z",
    end: "2026-10-02T00:45:00Z",
    grid: "10/01/2026, 18:45",
    date: "2026-10-01",
  },
  {
    name: "Chicago 7:30 PM CDT that is already tomorrow in UTC",
    zone: "America/Chicago",
    start: "2026-10-02T00:30:00Z",
    end: "2026-10-02T01:30:00Z",
    grid: "10/01/2026, 19:30",
    date: "2026-10-01",
  },
  {
    name: "Chicago the day before spring-forward (6:00 PM CST, Mar 7)",
    zone: "America/Chicago",
    start: "2026-03-08T00:00:00Z",
    end: "2026-03-08T01:00:00Z",
    grid: "03/07/2026, 18:00",
    date: "2026-03-07",
  },
  {
    name: "Chicago spring-forward day (6:00 PM CDT, Mar 8)",
    zone: "America/Chicago",
    start: "2026-03-08T23:00:00Z",
    end: "2026-03-09T00:00:00Z",
    grid: "03/08/2026, 18:00",
    date: "2026-03-08",
  },
  {
    name: "Chicago the day before fall-back (6:00 PM CDT, Oct 31)",
    zone: "America/Chicago",
    start: "2026-10-31T23:00:00Z",
    end: "2026-11-01T00:00:00Z",
    grid: "10/31/2026, 18:00",
    date: "2026-10-31",
  },
  {
    name: "Chicago fall-back day (6:00 PM CST, Nov 1)",
    zone: "America/Chicago",
    start: "2026-11-02T00:00:00Z",
    end: "2026-11-02T01:00:00Z",
    grid: "11/01/2026, 18:00",
    date: "2026-11-01",
  },
  {
    name: "Chicago Nov 5 6:00 PM CST (the #1045 occurrence)",
    zone: "America/Chicago",
    start: "2026-11-06T00:00:00Z",
    end: "2026-11-06T01:00:00Z",
    grid: "11/05/2026, 18:00",
    date: "2026-11-05",
  },
  {
    name: "Los Angeles academy 5:00 PM PDT",
    zone: "America/Los_Angeles",
    start: "2026-10-02T00:00:00Z",
    end: "2026-10-02T01:00:00Z",
    grid: "10/01/2026, 17:00",
    date: "2026-10-01",
  },
  {
    name: "New York academy 8:00 PM EDT",
    zone: "America/New_York",
    start: "2026-10-02T00:00:00Z",
    end: "2026-10-02T01:00:00Z",
    grid: "10/01/2026, 20:00",
    date: "2026-10-01",
  },
  {
    name: "date-ahead academy: Kolkata 5:00 AM IST is the previous UTC day",
    zone: "Asia/Kolkata",
    start: "2026-09-30T23:30:00Z",
    end: "2026-10-01T00:30:00Z",
    grid: "10/01/2026, 05:00",
    date: "2026-10-01",
  },
];

describe("persona calendars render in the academy zone (#1043)", () => {
  for (const f of FIXTURES) {
    it(`coach: ${f.name}`, () => {
      const { timeZone, events } = coachScheduleToCalendar([coachEntry(f.start, f.end, f.zone)]);
      expect(timeZone).toEqual({ status: "ready", timeZone: f.zone });
      if (timeZone.status !== "ready") return;
      expect(onGrid(events[0].start, timeZone.timeZone)).toBe(f.grid);
      // The event sits on the same day its detail link asks the backend for.
      expect(events[0].url).toBe(`/coach/sessions/occ-1?date=${f.date}`);
    });

    it(`parent: ${f.name}`, () => {
      const timeZone = resolveCalendarTimeZone([f.zone]);
      expect(timeZone).toEqual({ status: "ready", timeZone: f.zone });
      if (timeZone.status !== "ready") return;
      const event = scheduleEntryToEvent(parentEntry(f.start, f.end), {
        childName: "Ava",
        color: "#2563eb",
      });
      expect(onGrid(event.start, timeZone.timeZone)).toBe(f.grid);
    });
  }

  it("coach and parent place the same occurrence identically", () => {
    for (const f of FIXTURES) {
      const coach = coachScheduleToCalendar([coachEntry(f.start, f.end, f.zone)]).events[0];
      const parent = scheduleEntryToEvent(parentEntry(f.start, f.end), {
        childName: "Ava",
        color: "#2563eb",
      });
      expect(onGrid(coach.start, f.zone)).toBe(onGrid(parent.start, f.zone));
      expect(onGrid(coach.end ?? "", f.zone)).toBe(onGrid(parent.end ?? "", f.zone));
    }
  });

  it("keeps cancelled-class styling on the parent calendar", () => {
    const event = scheduleEntryToEvent(
      parentEntry("2026-11-06T00:00:00Z", "2026-11-06T01:00:00Z", "cancelled"),
      { childName: "Ava", color: "#2563eb" },
    );
    expect(event.title.startsWith("Cancelled — ")).toBe(true);
    expect(onGrid(event.start, "America/Chicago")).toBe("11/05/2026, 18:00");
  });

  it("'today' follows the academy zone, not the browser's", () => {
    // 10:30 PM on Oct 1 in Chicago is already Oct 2 in UTC, Tokyo, etc.
    expect(onGrid("2026-10-02T03:30:00Z", "America/Chicago").slice(0, 10)).toBe("10/01/2026");
    expect(onGrid("2026-10-02T03:30:00Z", "Asia/Tokyo").slice(0, 10)).toBe("10/02/2026");
  });

  it("would be wrong without the named-zone plugin (guards the dependency)", () => {
    // FullCalendar without a named-zone implementation treats a named zone
    // as UTC: the 6:00 PM Nov 5 class would sit on Nov 6 at midnight.
    const bare = formatDate("2026-11-06T00:00:00Z", {
      timeZone: "America/Chicago",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    expect(bare).not.toBe("11/05/2026, 18:00");
  });
});

describe("PersonaCalendarView wiring (#1043)", () => {
  const read = (rel: string) => readFileSync(join(__dirname, "..", "..", rel), "utf8");
  const view = read("components/calendar/PersonaCalendarView.tsx");

  it("registers the luxon named-zone plugin and passes the zone to FullCalendar", () => {
    expect(view).toContain('import luxonPlugin from "@fullcalendar/luxon3"');
    expect(view).toMatch(/plugins=\{\[dayGridPlugin, luxonPlugin\]\}/);
    expect(view).toMatch(/timeZone=\{timeZone\}/);
  });

  it("labels the clock it renders in", () => {
    expect(view).toContain('data-testid="calendar-timezone"');
    expect(view).toContain("calendarTimeZoneLabel(timeZone)");
  });

  it("keeps the mobile day view, desktop month/week views and the safe-URL guard", () => {
    expect(view).toContain('initialView={phone ? "dayGridDay" : "dayGridMonth"}');
    expect(view).toContain('"dayGridMonth,dayGridWeek"');
    expect(view).toContain('event.url.startsWith("/") && !event.url.startsWith("//")');
  });

  it("both persona pages pass a resolved zone and have an explicit unavailable state", () => {
    for (const page of [
      "app/(coach)/coach/calendar/page.tsx",
      "app/(parent)/parent/calendar/page.tsx",
    ]) {
      const src = read(page);
      expect(src).toMatch(/timeZone=\{\w+\.timeZone\}/);
      expect(src).toContain("<CalendarTimeZoneUnavailable");
    }
  });
});
