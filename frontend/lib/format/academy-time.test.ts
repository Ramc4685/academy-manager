import { describe, expect, it } from "vitest";

import { formatAcademyDay } from "./academy-time";

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
