import { describe, expect, it } from "vitest";

import type { AdminSessionOccurrenceView } from "@/lib/api/admin";
import { datesToCancel, groupMonthDates, monthCompleteFrom, plainDatesInMonth, scheduleAnnouncement } from "./month-dates";

const TZ = "America/Chicago";
const NOW = new Date("2026-11-17T12:00:00Z");

function occ(id: string, start: string, over: Partial<AdminSessionOccurrenceView> = {}) {
  return {
    occurrence_id: id,
    session_id: "s1",
    start_at: start,
    end_at: start,
    status: "scheduled",
    cancellation_reason: null,
    cancelled_at: null,
    scheduled_coach_id: "c1",
    actual_coach_id: null,
    substitute_coach_id: null,
    attendance_marked_count: 0,
    attendance_marked_by: [],
    attendance_last_marked_at: null,
    coach_attendance: [],
    ...over,
  } as AdminSessionOccurrenceView;
}

describe("groupMonthDates", () => {
  it("groups by the academy-local day and drops other months", () => {
    // 01:00Z on Dec 1 is still Nov 30 in Chicago.
    const dates = groupMonthDates(
      [
        { occurrence: occ("a", "2026-12-01T01:00:00Z"), sessionTitle: "A" },
        { occurrence: occ("b", "2026-12-05T16:00:00Z"), sessionTitle: "A" },
        { occurrence: occ("c", "2026-12-05T15:00:00Z"), sessionTitle: "B" },
      ],
      "2026-12",
      TZ,
    );
    expect(dates.map((d) => d.day)).toEqual(["2026-12-05"]);
    expect(dates[0].classes.map((c) => c.occurrence.occurrence_id)).toEqual(["c", "b"]);
  });
});

describe("datesToCancel", () => {
  it("only cancels unticked dates that are still live and in the future", () => {
    const dates = groupMonthDates(
      [
        { occurrence: occ("live", "2026-11-20T16:00:00Z"), sessionTitle: "A" },
        { occurrence: occ("past", "2026-11-10T16:00:00Z"), sessionTitle: "A" },
        { occurrence: occ("gone", "2026-11-27T16:00:00Z", { status: "cancelled" }), sessionTitle: "A" },
        { occurrence: occ("kept", "2026-11-24T16:00:00Z"), sessionTitle: "A" },
      ],
      "2026-11",
      TZ,
    );
    expect(datesToCancel(dates, new Set(["live", "past", "gone"]), NOW)).toEqual(["live"]);
  });
});

describe("scheduleAnnouncement", () => {
  it("lists class and no-class dates with the reason", () => {
    const body = scheduleAnnouncement(
      "Junior A",
      [
        occ("b", "2026-12-12T16:00:00Z", { status: "cancelled", cancellation_reason: "Gym closed" }),
        occ("a", "2026-12-05T16:00:00Z"),
      ],
      "December 2026",
      TZ,
    )!;
    expect(body).toContain("Junior A: December 2026 schedule is final.");
    expect(body).toMatch(/Class:\n- Sat, Dec 5/);
    expect(body).toMatch(/No class:\n- Sat, Dec 12 \(Gym closed\)/);
  });

  it("returns null for a class with no dates that month", () => {
    expect(scheduleAnnouncement("A", [], "December 2026", TZ)).toBeNull();
  });
});

describe("plainDatesInMonth", () => {
  const sorted = (s: Set<string>) => [...s].sort();

  it("reads single dates in every common spelling", () => {
    expect(sorted(plainDatesInMonth("No class Dec 8, December 15th, 12/1 and 2026-12-03", "2026-12"))).toEqual([
      "2026-12-01",
      "2026-12-03",
      "2026-12-08",
      "2026-12-15",
    ]);
  });

  it("fills spans, including across the new year", () => {
    expect(sorted(plainDatesInMonth("Gym closed Dec 21 - Jan 2", "2026-12"))).toEqual(
      Array.from({ length: 11 }, (_, i) => `2026-12-${21 + i}`),
    );
    expect(sorted(plainDatesInMonth("Gym closed Dec 21 - Jan 2", "2027-01"))).toEqual(["2027-01-01", "2027-01-02"]);
    expect(sorted(plainDatesInMonth("Closed Nov 26-27", "2026-11"))).toEqual(["2026-11-26", "2026-11-27"]);
  });

  it("does not read words before a number as a month", () => {
    expect(sorted(plainDatesInMonth("No class 12/22 and Dec 29", "2026-12"))).toEqual(["2026-12-22", "2026-12-29"]);
  });

  it("ignores other months, times and non-dates", () => {
    expect(sorted(plainDatesInMonth("Room 12, 6:30 pm, Jan 5, May 2", "2026-12"))).toEqual([]);
  });
});

describe("monthCompleteFrom", () => {
  const now = new Date("2026-11-20T18:00:00Z"); // Nov 20, noon in Chicago

  it("is null once the whole month is within the 60-day horizon", () => {
    expect(monthCompleteFrom("2026-12", now, "America/Chicago")).toBeNull();
    expect(monthCompleteFrom("2026-11", now, "America/Chicago")).toBeNull();
  });

  it("names the day a later month becomes complete", () => {
    expect(monthCompleteFrom("2027-01", now, "America/Chicago")).toBe("2026-12-02");
    expect(monthCompleteFrom("2027-03", now, "America/Chicago")).toBe("2027-01-30");
  });
});
