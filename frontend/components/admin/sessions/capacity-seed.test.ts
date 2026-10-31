import { describe, expect, it } from "vitest";

import { shouldAdoptAcademyCapacity } from "./capacity-seed";

describe("shouldAdoptAcademyCapacity (Issue #148 capacity follow-up)", () => {
  it("adopts the academy default when the query resolves after the dialog opened", () => {
    // Dialog opened before /admin/academy resolved (wasOpen was already true
    // on a prior render), the query has now settled, and the admin has not
    // touched capacity: adopt the real default instead of the hardcoded 10.
    expect(
      shouldAdoptAcademyCapacity({
        open: true,
        wasOpen: true,
        capacityTouched: false,
        defaultClassSize: 8,
      }),
    ).toBe(true);
  });

  it("does not re-seed on the same render the dialog opens", () => {
    // That render is handled by the initial-seed branch instead.
    expect(
      shouldAdoptAcademyCapacity({
        open: true,
        wasOpen: false,
        capacityTouched: false,
        defaultClassSize: 8,
      }),
    ).toBe(false);
  });

  it("does not override a capacity the admin already edited", () => {
    expect(
      shouldAdoptAcademyCapacity({
        open: true,
        wasOpen: true,
        capacityTouched: true,
        defaultClassSize: 8,
      }),
    ).toBe(false);
  });

  it("does nothing while the academy query is still loading", () => {
    expect(
      shouldAdoptAcademyCapacity({
        open: true,
        wasOpen: true,
        capacityTouched: false,
        defaultClassSize: undefined,
      }),
    ).toBe(false);
  });

  it("does nothing while the dialog is closed", () => {
    expect(
      shouldAdoptAcademyCapacity({
        open: false,
        wasOpen: true,
        capacityTouched: false,
        defaultClassSize: 8,
      }),
    ).toBe(false);
  });
});
