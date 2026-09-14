import { describe, expect, it } from "vitest";

import {
  departureLabel,
  departureReasonNote,
  isDepartedEnrollment,
} from "./departure-copy";

const formatDate = (iso: string) => (iso === "2026-06-01T09:00:00Z" ? "Jun 1, 2026" : "");

describe("isDepartedEnrollment", () => {
  it("only trusts the explicit flag, never the status spelling", () => {
    expect(isDepartedEnrollment({ departed: true })).toBe(true);
    expect(isDepartedEnrollment({ departed: false })).toBe(false);
    expect(isDepartedEnrollment({})).toBe(false);
  });
});

describe("departureLabel", () => {
  it("names the day the enrollment ended", () => {
    expect(departureLabel("2026-06-01T09:00:00Z", formatDate)).toBe("Ended Jun 1, 2026");
  });

  it("still says the class ended when the row carries no date", () => {
    expect(departureLabel(null, formatDate)).toBe("Ended");
    expect(departureLabel("not-a-date", formatDate)).toBe("Ended");
  });
});

describe("departureReasonNote", () => {
  it("prints a recorded reason and nothing for an empty one", () => {
    expect(departureReasonNote("move out of town")).toBe("Reason given: move out of town");
    expect(departureReasonNote("   ")).toBeNull();
    expect(departureReasonNote(null)).toBeNull();
  });
});
