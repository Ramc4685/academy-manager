import { describe, expect, it } from "vitest";

import { hasCoachRole } from "./coach-roles";

describe("hasCoachRole", () => {
  it("is true for a primary coach", () => {
    expect(hasCoachRole({ role: "coach", roles: ["coach"] })).toBe(true);
  });

  it("is true for an assistant coach", () => {
    expect(hasCoachRole({ role: "assistant_coach", roles: ["assistant_coach"] })).toBe(true);
  });

  it("is true for a multi-role user whose primary role is not coach", () => {
    expect(hasCoachRole({ role: "parent", roles: ["parent", "coach"] })).toBe(true);
    expect(hasCoachRole({ role: "admin", roles: ["admin", "assistant_coach"] })).toBe(true);
  });

  it("is false for a parent or admin with no coaching role", () => {
    expect(hasCoachRole({ role: "parent", roles: ["parent"] })).toBe(false);
    expect(hasCoachRole({ role: "admin", roles: ["admin", "owner"] })).toBe(false);
  });

  it("falls back to the primary role when roles is missing or empty", () => {
    expect(hasCoachRole({ role: "coach" })).toBe(true);
    expect(hasCoachRole({ role: "coach", roles: [] })).toBe(true);
    expect(hasCoachRole({ role: "parent", roles: null })).toBe(false);
  });
});
