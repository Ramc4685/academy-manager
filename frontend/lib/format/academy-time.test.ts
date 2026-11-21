import { describe, expect, it } from "vitest";

import { academyDateISO, academyMonthKey, formatAcademyDay } from "./academy-time";

describe("formatAcademyDay", () => {
  it("keeps a midnight-UTC calendar date on its own day", () => {
    expect(formatAcademyDay("2026-11-05T00:00:00Z", "America/Chicago")).toBe("Thu, Nov 5");
    expect(formatAcademyDay("2026-11-05T00:00:00", "America/Chicago")).toBe("Thu, Nov 5");
  });

  it("formats a real instant in the academy timezone", () => {
    // 02:30Z on Nov 6 is 8:30 PM Nov 5 in Chicago.
    expect(formatAcademyDay("2026-11-06T02:30:00Z", "America/Chicago")).toBe("Thu, Nov 5");
  });

  it("returns empty for garbage", () => {
    expect(formatAcademyDay("not-a-date", "America/Chicago")).toBe("");
  });
});

describe("academyDateISO / academyMonthKey (L2 A0-3)", () => {
  // 9:30 PM on Sep 30 in Chicago is 02:30Z on Oct 1.
  const evening = new Date("2026-10-01T02:30:00Z");

  it("uses the academy's date, not the UTC date, in the evening", () => {
    expect(evening.toISOString().slice(0, 10)).toBe("2026-10-01");
    expect(academyDateISO("America/Chicago", evening)).toBe("2026-09-30");
  });

  it("keeps the academy's month on the last evening of the month", () => {
    expect(academyMonthKey("America/Chicago", 0, evening)).toBe("2026-09");
    expect(academyMonthKey("America/Chicago", -1, evening)).toBe("2026-08");
    expect(academyMonthKey("America/Chicago", -1, new Date("2026-01-15T12:00:00Z"))).toBe(
      "2025-12",
    );
  });
});
