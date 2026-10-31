import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import type { CoachScheduleEntry } from "@/lib/api/coach";
import { sessionDateKey } from "@/lib/time/session-time";

import { coachScheduleEntryHref, coachScheduleToCalendar } from "./schedule-links";

/**
 * #1045 — Coach Sessions linked an evening class to the UTC date
 * (`start_at.slice(0, 10)`), so a 6:00 PM Chicago class on Nov 5 asked the
 * session screen for Nov 6 and rendered "Session not found."
 *
 * Every case is a class whose local date differs from (or sits right next
 * to) its UTC date. These are pure Intl computations: the expected dates do
 * not depend on the machine's TZ, and CI runs the suite under several.
 */

function entry(overrides: Partial<CoachScheduleEntry>): CoachScheduleEntry {
  return {
    session_id: "sess-1",
    occurrence_id: "occ-1",
    title: "Juniors",
    location: "Court 1",
    timezone: "America/Chicago",
    start_at: "2026-11-06T00:00:00Z",
    end_at: "2026-11-06T01:00:00Z",
    ...overrides,
  };
}

const CASES: Array<{ name: string; start_at: string; timezone: string; date: string }> = [
  {
    name: "Chicago winter evening (6:00 PM CST, Nov 5 = Nov 6 UTC) — the live repro",
    start_at: "2026-11-06T00:00:00Z",
    timezone: "America/Chicago",
    date: "2026-11-05",
  },
  {
    name: "Chicago winter evening 6:45 PM CST",
    start_at: "2026-11-06T00:45:00Z",
    timezone: "America/Chicago",
    date: "2026-11-05",
  },
  {
    name: "Chicago summer evening (7:30 PM CDT, Jul 9 = Jul 10 UTC)",
    start_at: "2026-07-10T00:30:00Z",
    timezone: "America/Chicago",
    date: "2026-07-09",
  },
  {
    name: "Chicago summer evening that stays on the UTC date (6:00 PM CDT)",
    start_at: "2026-07-09T23:00:00Z",
    timezone: "America/Chicago",
    date: "2026-07-09",
  },
  {
    name: "positive-offset academy: 5:00 AM IST Mar 10 is still Mar 9 in UTC",
    start_at: "2026-03-09T23:30:00Z",
    timezone: "Asia/Kolkata",
    date: "2026-03-10",
  },
  {
    name: "positive-offset academy: 7:00 AM NZDT Jan 15 is Jan 14 in UTC",
    start_at: "2026-01-14T18:00:00Z",
    timezone: "Pacific/Auckland",
    date: "2026-01-15",
  },
  {
    name: "UTC academy: the UTC date is the local date",
    start_at: "2026-03-09T23:30:00Z",
    timezone: "UTC",
    date: "2026-03-09",
  },
  {
    name: "spring-forward day (Mar 8 2026): 7:00 PM CDT = Mar 9 00:00 UTC",
    start_at: "2026-03-09T00:00:00Z",
    timezone: "America/Chicago",
    date: "2026-03-08",
  },
  {
    name: "fall-back day (Nov 1 2026): 6:00 PM CST = Nov 2 00:00 UTC",
    start_at: "2026-11-02T00:00:00Z",
    timezone: "America/Chicago",
    date: "2026-11-01",
  },
  {
    name: "fall-back day, before the switch: 12:30 AM CDT Nov 1 = 05:30 UTC",
    start_at: "2026-11-01T05:30:00Z",
    timezone: "America/Chicago",
    date: "2026-11-01",
  },
];

describe("coachScheduleEntryHref (#1045)", () => {
  for (const c of CASES) {
    it(c.name, () => {
      const e = entry({ start_at: c.start_at, timezone: c.timezone });
      expect(coachScheduleEntryHref(e)).toBe(`/coach/sessions/occ-1?date=${c.date}`);
    });
  }

  it("agrees with the date header the Sessions list groups the class under", () => {
    for (const c of CASES) {
      const e = entry({ start_at: c.start_at, timezone: c.timezone });
      expect(coachScheduleEntryHref(e)).toContain(`?date=${sessionDateKey(e.start_at, e.timezone)}`);
    }
  });

  it("is the same link the Calendar builds for the same occurrence", () => {
    for (const c of CASES) {
      const e = entry({ start_at: c.start_at, timezone: c.timezone });
      const { events } = coachScheduleToCalendar([e]);
      expect(events[0].url).toBe(coachScheduleEntryHref(e));
    }
  });

  it("dates a zone-less entry on the fallback (grid) zone, not UTC", () => {
    const e = entry({ timezone: null, start_at: "2026-11-06T00:00:00Z" });
    expect(coachScheduleEntryHref(e, "America/Chicago")).toBe(
      "/coach/sessions/occ-1?date=2026-11-05",
    );
    // A class's own zone still wins over the fallback.
    expect(
      coachScheduleEntryHref(entry({ timezone: "UTC" }), "America/Chicago"),
    ).toBe("/coach/sessions/occ-1?date=2026-11-06");
  });

  it("keeps the exact occurrence id, encoded", () => {
    const e = entry({ occurrence_id: "occ/7 a", start_at: "2026-11-06T00:00:00Z" });
    expect(coachScheduleEntryHref(e)).toBe("/coach/sessions/occ%2F7%20a?date=2026-11-05");
  });
});

describe("Coach Sessions page wiring (#1045)", () => {
  const page = readFileSync(
    join(__dirname, "..", "..", "app", "(coach)", "coach", "sessions", "page.tsx"),
    "utf8",
  );

  it("builds its detail links with the shared local-date helper", () => {
    expect(page).toContain("coachScheduleEntryHref(session)");
  });

  it("no longer slices the UTC date or cites the obsolete UTC day bounds", () => {
    expect(page).not.toMatch(/start_at\.slice\(0,\s*10\)/);
    expect(page).not.toContain("_day_bounds_utc");
  });
});

describe("Coach Today page wiring (#1045)", () => {
  const page = readFileSync(
    join(__dirname, "..", "..", "app", "(coach)", "coach", "today", "page.tsx"),
    "utf8",
  );

  it("builds its recent-unmarked links with the shared local-date helper", () => {
    expect(page).toContain("coachScheduleEntryHref(s)");
    expect(page).not.toMatch(/coachSessionHref\(\s*s\.occurrence_id,\s*sessionDateKey/);
  });
});

describe("coachScheduleToCalendar (#1043)", () => {
  it("runs the grid on the sessions' zone and pins explicit UTC instants", () => {
    const { timeZone, events } = coachScheduleToCalendar([
      entry({ start_at: "2026-11-06T00:00:00", end_at: "2026-11-06T01:00:00" }),
    ]);
    expect(timeZone).toEqual({ status: "ready", timeZone: "America/Chicago" });
    // A naive backend timestamp is UTC; FullCalendar would otherwise read it
    // as wall time in the calendar zone and shift the class by 6 hours.
    expect(events[0].start).toBe("2026-11-06T00:00:00.000Z");
    expect(events[0].end).toBe("2026-11-06T01:00:00.000Z");
    expect(events[0].url).toBe("/coach/sessions/occ-1?date=2026-11-05");
  });

  it("links a zone-less entry on the grid's local date (#1045)", () => {
    const { events } = coachScheduleToCalendar([
      entry({ occurrence_id: "occ-a" }),
      entry({ occurrence_id: "occ-b", timezone: null }),
    ]);
    // 00:00Z Nov 6 is 6:00 PM Nov 5 on the Chicago grid; the link agrees.
    expect(events[1].url).toBe("/coach/sessions/occ-b?date=2026-11-05");
  });

  it("is unavailable — not the browser zone — when no entry has a valid zone", () => {
    expect(coachScheduleToCalendar([entry({ timezone: null })]).timeZone).toEqual({
      status: "unavailable",
    });
    expect(coachScheduleToCalendar([entry({ timezone: "Mars/Olympus" })]).timeZone).toEqual({
      status: "unavailable",
    });
    expect(coachScheduleToCalendar([]).timeZone).toEqual({ status: "unavailable" });
  });
});
