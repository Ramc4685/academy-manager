import { describe, expect, it } from "vitest";

import {
  academyDateISO,
  academyMonthKey,
  formatAcademyDay,
  formatAcademyStamp,
  formatInAcademyZone,
  setAmbientAcademyZone,
} from "./academy-time";
import { formatPlainDate } from "./plain-date";

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

describe("formatInAcademyZone / formatAcademyStamp (S05)", () => {
  // 03:30Z on Nov 6 is still Nov 5 in Chicago but already Nov 6 in Kolkata.
  const lateEvening = "2026-11-06T03:30:00Z";

  it("puts an instant on the academy's day, not the viewer's", () => {
    expect(formatInAcademyZone(lateEvening, "America/Chicago")).toBe("Nov 5, 2026");
    expect(formatInAcademyZone(lateEvening, "Asia/Kolkata")).toBe("Nov 6, 2026");
  });

  it("stamps a logged moment with the academy's clock and zone label", () => {
    expect(formatAcademyStamp(lateEvening, "America/Chicago")).toBe("Nov 5, 2026, 9:30 PM CST");
  });

  it("uses the shell's academy zone when the caller passes none", () => {
    setAmbientAcademyZone("America/Chicago");
    try {
      expect(formatInAcademyZone(lateEvening)).toBe("Nov 5, 2026");
      // An explicit zone still wins over the shell's.
      expect(formatInAcademyZone(lateEvening, "Asia/Kolkata")).toBe("Nov 6, 2026");
    } finally {
      setAmbientAcademyZone(null);
    }
  });

  it("returns empty for missing or garbage values", () => {
    expect(formatInAcademyZone(null, "America/Chicago")).toBe("");
    expect(formatInAcademyZone("", "America/Chicago")).toBe("");
    expect(formatInAcademyZone("not-a-date", "America/Chicago")).toBe("");
  });

  it("keeps a date-only value on its calendar day in every zone", () => {
    setAmbientAcademyZone("Pacific/Honolulu");
    try {
      expect(formatPlainDate("2026-12-01", { month: "short", day: "numeric", year: "numeric" })).toBe(
        "Dec 1, 2026",
      );
      expect(formatAcademyDay("2026-12-01T00:00:00Z", "Pacific/Honolulu", { month: "short", day: "numeric" })).toBe(
        "Dec 1",
      );
    } finally {
      setAmbientAcademyZone(null);
    }
  });
});
