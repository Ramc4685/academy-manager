import { describe, expect, it } from "vitest";

import {
  calendarInstant,
  calendarTimeZoneLabel,
  isValidTimeZone,
  resolveCalendarTimeZone,
} from "./calendar-timezone";

describe("resolveCalendarTimeZone (#1043)", () => {
  it("uses the academy/session zone when it is a real IANA zone", () => {
    expect(resolveCalendarTimeZone(["America/Chicago"])).toEqual({
      status: "ready",
      timeZone: "America/Chicago",
    });
    expect(resolveCalendarTimeZone(["  Asia/Kolkata "])).toEqual({
      status: "ready",
      timeZone: "Asia/Kolkata",
    });
  });

  it("has an explicit unavailable state for missing / blank / invalid zones", () => {
    for (const candidates of [[], [null], [undefined], [""], ["   "], ["Not/AZone"], ["CDT-ish"]]) {
      expect(resolveCalendarTimeZone(candidates)).toEqual({ status: "unavailable" });
    }
  });

  it("skips blanks and invalid names next to a valid zone", () => {
    expect(resolveCalendarTimeZone([null, "Nope/Zone", "America/Chicago", ""])).toEqual({
      status: "ready",
      timeZone: "America/Chicago",
    });
  });

  it("picks the most common zone when entries disagree (ties: first seen)", () => {
    expect(
      resolveCalendarTimeZone(["America/New_York", "America/Chicago", "America/Chicago"]),
    ).toEqual({ status: "ready", timeZone: "America/Chicago" });
    expect(resolveCalendarTimeZone(["America/New_York", "America/Chicago"])).toEqual({
      status: "ready",
      timeZone: "America/New_York",
    });
  });

  it("validates names with Intl", () => {
    expect(isValidTimeZone("America/Los_Angeles")).toBe(true);
    expect(isValidTimeZone("UTC")).toBe(true);
    expect(isValidTimeZone("America/Nowhere")).toBe(false);
  });
});

describe("calendarInstant", () => {
  it("treats naive backend timestamps as UTC", () => {
    expect(calendarInstant("2026-10-01T23:00:00")).toBe("2026-10-01T23:00:00.000Z");
  });

  it("keeps explicit instants, normalised to UTC", () => {
    expect(calendarInstant("2026-10-01T23:00:00Z")).toBe("2026-10-01T23:00:00.000Z");
    expect(calendarInstant("2026-10-01T18:00:00-05:00")).toBe("2026-10-01T23:00:00.000Z");
  });

  it("passes an unparseable value through untouched", () => {
    expect(calendarInstant("not a date")).toBe("not a date");
  });
});

describe("calendarTimeZoneLabel", () => {
  it("names the zone generically so it is right on both sides of DST", () => {
    expect(calendarTimeZoneLabel("America/Chicago")).toBe(
      "Times in Central Time (America/Chicago)",
    );
    expect(calendarTimeZoneLabel("America/Los_Angeles")).toBe(
      "Times in Pacific Time (America/Los_Angeles)",
    );
  });

  it("always includes the IANA name", () => {
    expect(calendarTimeZoneLabel("UTC")).toContain("UTC");
    expect(calendarTimeZoneLabel("Asia/Kolkata")).toContain("Asia/Kolkata");
  });
});
