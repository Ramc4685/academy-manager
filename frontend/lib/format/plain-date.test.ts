import { describe, expect, it } from "vitest";

import { formatPlainDate, formatPlainDateRange } from "./plain-date";

describe("formatPlainDate", () => {
  it("renders a calendar date as words, not as an ISO string (#841)", () => {
    expect(formatPlainDate("2026-07-15")).toBe("Wed, Jul 15");
  });

  it("does not shift the day for viewers west of UTC", () => {
    // A plain date has no instant attached; reading it in a local zone is how
    // "2026-07-15" turns into "Jul 14" for a Chicago admin.
    expect(formatPlainDate("2026-01-01")).toBe("Thu, Jan 1");
  });

  it("returns the input unchanged when it is not a calendar date", () => {
    expect(formatPlainDate("sometime")).toBe("sometime");
    expect(formatPlainDate("")).toBe("");
  });
});

describe("formatPlainDateRange", () => {
  it("joins two calendar dates with an en dash", () => {
    expect(formatPlainDateRange("2026-07-15", "2026-07-22")).toBe("Wed, Jul 15 – Wed, Jul 22");
  });

  it("collapses to one date when both ends are the same day", () => {
    expect(formatPlainDateRange("2026-07-15", "2026-07-15")).toBe("Wed, Jul 15");
  });

  it("shows whichever end it has", () => {
    expect(formatPlainDateRange("2026-07-15", "")).toBe("Wed, Jul 15");
    expect(formatPlainDateRange("", "")).toBe("—");
  });
});
