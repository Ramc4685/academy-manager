import { describe, expect, it } from "vitest";
import { formatCents, formatDateOnly, formatInstantDay, parseDollarsToCents } from "./money";

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

describe("formatInstantDay", () => {
  it("shows the viewer-local day of a timestamp and dashes for empty", () => {
    const local = new Date("2026-09-08T02:30:00Z");
    const expected = local.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    expect(formatInstantDay("2026-09-08T02:30:00Z")).toBe(expected);
    expect(formatInstantDay(null)).toBe("—");
    expect(formatInstantDay("not a date")).toBe("—");
  });
});

describe("parseDollarsToCents", () => {
  it("accepts plain amounts, $ and thousands separators", () => {
    expect(parseDollarsToCents("70")).toBe(7000);
    expect(parseDollarsToCents(" 70.50 ")).toBe(7050);
    expect(parseDollarsToCents("$1,234.5")).toBe(123450);
  });
  it("refuses anything ambiguous instead of guessing", () => {
    expect(parseDollarsToCents("12 34")).toBe(-1);
    expect(parseDollarsToCents("12.345")).toBe(-1);
    expect(parseDollarsToCents("abc")).toBe(-1);
    expect(parseDollarsToCents("")).toBe(-1);
  });
});
