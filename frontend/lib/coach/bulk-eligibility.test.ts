import { describe, expect, it } from "vitest";

import { isBulkMarkEligible } from "./bulk-eligibility";

describe("isBulkMarkEligible", () => {
  it("keeps an ordinary active row", () => {
    expect(isBulkMarkEligible({ enrollment_status: "active" })).toBe(true);
  });

  it("drops an on-hold seat the bulk endpoint would reject", () => {
    expect(isBulkMarkEligible({ enrollment_status: "held" })).toBe(false);
    expect(
      isBulkMarkEligible({ enrollment_status: "held", hold_return_on: "2026-10-15" }),
    ).toBe(false);
  });

  it("drops a seat mid-reclaim — the row already reads ON HOLD", () => {
    expect(isBulkMarkEligible({ enrollment_status: "reclaim_pending" })).toBe(false);
  });

  it("drops a student whose parent gave notice of absence", () => {
    expect(isBulkMarkEligible({ enrollment_status: "active", expected_absence: true })).toBe(
      false,
    );
  });

  it("keeps a row whose parent notice was withdrawn", () => {
    expect(isBulkMarkEligible({ enrollment_status: "active", expected_absence: false })).toBe(
      true,
    );
  });

  it("keeps a one-time make-up or trial row (no standing enrollment status)", () => {
    expect(isBulkMarkEligible({ entry_source: "makeup" })).toBe(true);
    expect(isBulkMarkEligible({ entry_source: "trial" })).toBe(true);
  });

  it("keeps a row whose status the client cannot rule out — the server decides", () => {
    // paused / cancelled and anything newer stay with the #672 rejection
    // path rather than being guessed at here.
    expect(isBulkMarkEligible({})).toBe(true);
    expect(isBulkMarkEligible({ enrollment_status: "paused" })).toBe(true);
  });
});
