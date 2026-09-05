import { describe, expect, it } from "vitest";
import { formatCents, formatDateOnly } from "./money";

describe("formatCents", () => {
  it("formats cents as USD with two decimals", () => {
    expect(formatCents(111000)).toBe("$1,110.00");
    expect(formatCents(0)).toBe("$0.00");
    expect(formatCents(5)).toBe("$0.05");
  });

  it("drops the decimals when whole is requested", () => {
    expect(formatCents(111000, { whole: true })).toBe("$1,110");
    expect(formatCents(0, { whole: true })).toBe("$0");
  });

  it("keeps the sign on negative amounts", () => {
    expect(formatCents(-2550)).toBe("-$25.50");
  });
});

describe("formatDateOnly", () => {
  it("renders a YYYY-MM-DD string as a short date", () => {
    expect(formatDateOnly("2026-09-08")).toBe("Sep 8, 2026");
    expect(formatDateOnly("2026-01-31")).toBe("Jan 31, 2026");
  });

  it("does not shift the day for ISO datetimes", () => {
    expect(formatDateOnly("2026-09-08T23:30:00Z")).toBe("Sep 8, 2026");
  });

  it("renders an em dash when the value is empty", () => {
    expect(formatDateOnly(null)).toBe("—");
    expect(formatDateOnly(undefined)).toBe("—");
    expect(formatDateOnly("")).toBe("—");
  });
});
