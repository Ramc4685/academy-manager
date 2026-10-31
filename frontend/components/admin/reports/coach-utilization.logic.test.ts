import { describe, expect, it } from "vitest";

import { formatRatePercent } from "./coach-utilization.logic";

/**
 * Issue #892 — the coach utilization report printed "NaN%".
 *
 * `Intl.NumberFormat(...).format(NaN)` renders the literal string "NaN%", and
 * a coach with no scheduled hours makes the backend divide zero by zero.
 */
describe("formatRatePercent (#892)", () => {
  it("never renders NaN, Infinity or undefined as a percentage", () => {
    expect(formatRatePercent(Number.NaN)).toBe("No data");
    expect(formatRatePercent(0 / 0)).toBe("No data");
    expect(formatRatePercent(Number.POSITIVE_INFINITY)).toBe("No data");
    expect(formatRatePercent(undefined)).toBe("No data");
  });

  it("says 'No data' for a missing rate, the way the compliance column did", () => {
    expect(formatRatePercent(null)).toBe("No data");
  });

  it("still formats a real rate", () => {
    expect(formatRatePercent(0)).toBe("0%");
    expect(formatRatePercent(0.625)).toBe("63%");
    expect(formatRatePercent(1)).toBe("100%");
  });
});
