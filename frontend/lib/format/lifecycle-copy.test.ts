import { describe, expect, it } from "vitest";

import {
  ALL_LIFECYCLES,
  OPERATIONAL_LIFECYCLES,
  formatLifecycleDate,
  lifecycleLabel,
  lifecycleName,
  lifecycleVariant,
} from "./lifecycle-copy";

describe("lifecycleLabel", () => {
  it("folds the date into the states that carry one", () => {
    expect(lifecycleLabel("on_hold", "2026-10-15")).toBe("ON HOLD until Oct 15, 2026");
    expect(lifecycleLabel("paused", "2026-11-01")).toBe("PAUSED until Nov 1, 2026");
    expect(lifecycleLabel("pending_cancel", "2026-10-31")).toBe("ENDS Oct 31, 2026");
    expect(lifecycleLabel("left", "2026-03-02")).toBe("LEFT Mar 2, 2026");
  });

  it("falls back to the bare state when there is no date", () => {
    expect(lifecycleLabel("on_hold", null)).toBe("ON HOLD");
    expect(lifecycleLabel("paused", undefined)).toBe("PAUSED");
    expect(lifecycleLabel("active", "2026-10-15")).toBe("ACTIVE");
  });

  it("renders nothing rather than throwing when the field is absent", () => {
    // A cached page from before #773 carries no lifecycle at all.
    expect(lifecycleLabel(undefined)).toBe("");
    expect(lifecycleLabel(null, "2026-10-15")).toBe("");
    expect(lifecycleVariant(undefined)).toBe("draft");
  });

  it("renders an unknown state verbatim instead of dropping the row", () => {
    // #714: a row the UI could not classify simply disappeared. Showing an
    // unfamiliar state is always better than showing no student.
    expect(lifecycleLabel("on_hold_reclaiming", null)).toBe("ON HOLD RECLAIMING");
    expect(lifecycleVariant("on_hold_reclaiming")).toBe("draft");
  });
});

describe("formatLifecycleDate", () => {
  it("treats the value as a calendar date, not an instant", () => {
    // Same day in every timezone the app runs in — a resume date that shifts
    // by one for a parent in another zone is a support ticket.
    expect(formatLifecycleDate("2026-01-01")).toBe("Jan 1, 2026");
  });

  it("returns empty for missing or malformed input", () => {
    expect(formatLifecycleDate(null)).toBe("");
    expect(formatLifecycleDate("")).toBe("");
    expect(formatLifecycleDate("15/10/2026")).toBe("");
  });
});

describe("lifecycleName", () => {
  it("sentence-cases the state for filters and tiles", () => {
    expect(lifecycleName("on_hold")).toBe("On hold");
    expect(lifecycleName("at_risk")).toBe("At risk");
    expect(lifecycleName("never_enrolled")).toBe("Not enrolled");
  });
});

describe("filter sets", () => {
  it("defaults the directory to everyone still on the books", () => {
    expect(OPERATIONAL_LIFECYCLES).toEqual(["active", "on_hold", "paused", "at_risk"]);
  });

  it("every operational state is also offered as its own filter", () => {
    for (const state of OPERATIONAL_LIFECYCLES) {
      expect(ALL_LIFECYCLES).toContain(state);
    }
  });
});
