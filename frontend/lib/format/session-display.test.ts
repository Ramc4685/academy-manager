/**
 * Regression coverage for the parent "Review & pay" time display.
 *
 * Production symptom: a real 6:00 PM Chicago class was shown to the parent as
 * "1:00 PM" — exactly the CDT (UTC-5) offset. The formatter used
 * `toLocaleTimeString(undefined, …)` with no `timeZone`, so it rendered the
 * viewer's browser zone rather than the academy's.
 *
 * Every assertion passes an explicit zone rather than relying on the runtime's
 * own, so a regression back to browser-zone rendering fails on any machine
 * instead of passing by coincidence on one that happens to be in Chicago.
 */

import { describe, expect, it } from "vitest";

import { academyTimeZoneLabel } from "./academy-time";
import {
  formatAcademyMoment,
  formatSessionOccurrence,
  sessionDisplayZone,
} from "./session-display";

// 2026-09-03 23:00Z == 6:00 PM CDT. Sep 3 2026 is a Thursday.
const START = "2026-09-03T23:00:00Z";
const END = "2026-09-03T23:45:00Z";

const RUNTIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

describe("formatSessionOccurrence", () => {
  it("renders the session's own timezone, not the viewer's", () => {
    expect(
      formatSessionOccurrence(
        { start_at: START, end_at: END, timezone: "America/Chicago" },
        null,
      ),
    ).toBe("Thu, Sep 3 · 6:00 PM – 6:45 PM CDT");
  });

  it("falls back to the academy timezone when the session has none", () => {
    expect(
      formatSessionOccurrence({ start_at: START, end_at: END, timezone: null }, "America/Chicago"),
    ).toBe("Thu, Sep 3 · 6:00 PM – 6:45 PM CDT");
  });

  it("prefers the session timezone over the academy timezone", () => {
    // 23:00Z is 4:30 AM the next day in Kolkata (UTC+5:30).
    expect(
      formatSessionOccurrence(
        { start_at: START, end_at: END, timezone: "Asia/Kolkata" },
        "America/Chicago",
      ),
    ).toBe("Fri, Sep 4 · 4:30 AM – 5:15 AM GMT+5:30");
  });

  it("never silently renders the browser zone without a visible label", () => {
    const out = formatSessionOccurrence(
      { start_at: START, end_at: END, timezone: null },
      null,
    );
    // Browser-zone fallback is allowed, but it must announce itself so the
    // reader can tell the hour is not the academy's.
    const label = academyTimeZoneLabel(new Date(START), RUNTIME_ZONE);
    expect(out.endsWith(` ${label}`)).toBe(true);
  });

  it("reproduces the reported defect only when the stored zone really is UTC", () => {
    // A session doc whose `timezone` field says "UTC" while the class is at
    // 6:00 PM Chicago is stored as 18:00Z — and 18:00Z IS 1:00 PM in Chicago.
    // Correct rendering of bad data; the data itself needs the migration.
    expect(
      formatSessionOccurrence(
        {
          start_at: "2026-09-03T18:00:00Z",
          end_at: "2026-09-03T18:45:00Z",
          timezone: "America/Chicago",
        },
        null,
      ),
    ).toBe("Thu, Sep 3 · 1:00 PM – 1:45 PM CDT");
  });

  it("treats an offset-less timestamp as UTC, not as browser-local wall clock", () => {
    // The catalog emits naive strings for rows read straight out of Mongo.
    // `new Date("2026-09-03T23:00:00")` would read that as 23:00 New York.
    expect(
      formatSessionOccurrence(
        {
          start_at: "2026-09-03T23:00:00",
          end_at: "2026-09-03T23:45:00",
          timezone: "America/Chicago",
        },
        null,
      ),
    ).toBe("Thu, Sep 3 · 6:00 PM – 6:45 PM CDT");
  });
});

describe("sessionDisplayZone", () => {
  it("prefers the session zone", () => {
    expect(sessionDisplayZone({ timezone: "Asia/Kolkata" }, "America/Chicago")).toBe(
      "Asia/Kolkata",
    );
  });

  it("falls back to the academy zone", () => {
    expect(sessionDisplayZone({ timezone: null }, "America/Chicago")).toBe("America/Chicago");
  });

  it("ignores a blank session zone rather than treating it as a zone", () => {
    expect(sessionDisplayZone({ timezone: "   " }, "America/Chicago")).toBe("America/Chicago");
  });

  it("returns null when nothing is known, never a guessed 'UTC'", () => {
    expect(sessionDisplayZone({ timezone: null }, null)).toBeNull();
  });
});

describe("formatAcademyMoment", () => {
  it("renders a single timestamp in the academy zone with a label", () => {
    expect(formatAcademyMoment(START, "America/Chicago")).toBe("Thu, Sep 3 · 6:00 PM CDT");
  });
});
