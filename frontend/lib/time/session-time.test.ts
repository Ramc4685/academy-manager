import { describe, expect, it } from "vitest";

import {
  LAST_RESORT_TIMEZONE,
  formatSessionTimeRange,
  sessionDateKey,
  sessionTimezone,
} from "./session-time";

// 23:00Z on 2026-09-03 is 6:00 PM in Chicago (BLNO) and 4:00 PM in LA.
const START = "2026-09-03T23:00:00Z";
const END = "2026-09-03T23:45:00Z";

describe("sessionTimezone", () => {
  it("uses the session's own zone first", () => {
    expect(sessionTimezone("America/Chicago", "America/Los_Angeles")).toBe("America/Chicago");
  });

  it("falls back to the academy zone when the session has none", () => {
    expect(sessionTimezone(null, "America/Chicago")).toBe("America/Chicago");
    expect(sessionTimezone("  ", "America/Los_Angeles")).toBe("America/Los_Angeles");
  });

  it("uses UTC only as the last resort", () => {
    expect(LAST_RESORT_TIMEZONE).toBe("UTC");
    expect(sessionTimezone(null)).toBe("UTC");
    expect(sessionTimezone(undefined, "")).toBe("UTC");
  });
});

describe("formatSessionTimeRange", () => {
  it("renders a BLNO session in Chicago time (unchanged)", () => {
    expect(formatSessionTimeRange(START, END, "America/Chicago")).toBe(
      formatSessionTimeRange(START, END, null, "America/Chicago"),
    );
    expect(formatSessionTimeRange(START, END, "America/Chicago")).toMatch(/6:00\s?PM/);
  });

  it("renders a zoneless session on the academy's clock, not UTC", () => {
    expect(formatSessionTimeRange(START, END, null, "America/Los_Angeles")).toMatch(/4:00\s?PM/);
    expect(formatSessionTimeRange(START, END, null)).toMatch(/11:00\s?PM/);
  });
});

describe("sessionDateKey", () => {
  it("buckets by the academy's calendar day when the session has no zone", () => {
    // 02:00Z on the 4th is still the evening of the 3rd in Chicago.
    expect(sessionDateKey("2026-09-04T02:00:00Z", null, "America/Chicago")).toBe("2026-09-03");
    expect(sessionDateKey("2026-09-04T02:00:00Z", null)).toBe("2026-09-04");
  });
});
