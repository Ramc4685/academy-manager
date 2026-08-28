import { describe, expect, it } from "vitest";

import { formatDate, formatDateUtc, formatInvoiceDate } from "./format";

// Issue #215: invoice dates stored at UTC midnight rendered a day early in US
// timezones. These assertions pin the split between calendar dates (UTC) and
// real instants (local). Only the numeric parts are asserted, normalised so the
// order, separators and zero-padding of the runner's locale do not matter
// (en-US renders 6/1/2026, en-GB renders 01/06/2026).
function parts(rendered: string) {
  return (rendered.match(/\d+/g) ?? []).map((part) => String(Number(part)));
}

describe("formatDateUtc", () => {
  it("renders a UTC-midnight timestamp on its stored calendar day", () => {
    // Would render as 5/31/2026 with a bare toLocaleDateString() in US zones.
    expect(parts(formatDateUtc("2026-06-01T00:00:00.000Z"))).toEqual(
      expect.arrayContaining(["6", "1", "2026"]),
    );
  });

  it("renders a date-only string on that same day", () => {
    expect(parts(formatDateUtc("2026-06-01"))).toEqual(
      expect.arrayContaining(["6", "1", "2026"]),
    );
  });

  it("does not shift a late-evening UTC timestamp forward", () => {
    expect(parts(formatDateUtc("2026-06-01T23:59:00.000Z"))).toEqual(
      expect.arrayContaining(["6", "1", "2026"]),
    );
  });

  it("returns a dash for empty values", () => {
    expect(formatDateUtc(null)).toBe("—");
    expect(formatDateUtc(undefined)).toBe("—");
    expect(formatDateUtc("")).toBe("—");
  });
});

describe("formatDate", () => {
  it("still renders real instants in the viewer's local timezone", () => {
    const value = "2026-06-01T18:30:00.000Z";
    expect(formatDate(value)).toBe(new Date(value).toLocaleDateString());
  });

  it("returns a dash for empty values", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("formatInvoiceDate", () => {
  it("renders a UTC-midnight invoice on its stored calendar day", () => {
    // The reported bug: rendered 5/31/2026 in US timezones before the fix.
    expect(parts(formatInvoiceDate("2026-06-01T00:00:00.000Z"))).toEqual(
      expect.arrayContaining(["6", "1", "2026"]),
    );
  });

  it("keeps an invoice with a real time-of-day on the viewer's local day", () => {
    // A payment recorded at 20:00 America/Chicago lands at 01:00Z the next day;
    // rendering that in UTC would move it forward a day for the admin who
    // recorded it.
    const value = "2026-06-16T01:00:00.000Z";
    expect(formatInvoiceDate(value)).toBe(new Date(value).toLocaleDateString());
  });

  it("returns a dash for empty and unparseable values", () => {
    expect(formatInvoiceDate(null)).toBe("—");
    expect(formatInvoiceDate("")).toBe("—");
    expect(formatInvoiceDate("not-a-date")).toBe("—");
  });
});
