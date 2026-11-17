import { describe, expect, it } from "vitest";

import { assignableCoaches, hasCoachRole, syncRolesDraft } from "./coach-roles";

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

describe("assignableCoaches", () => {
  const users = [
    { user_id: "a", status: "active" },
    { user_id: "d", status: "disabled" },
    { user_id: "i", status: "inactive" },
  ];

  it("offers only active coaches", () => {
    expect(assignableCoaches(users).map((u) => u.user_id)).toEqual(["a"]);
  });

  it("keeps the coach already assigned so the select shows it", () => {
    expect(assignableCoaches(users, "d").map((u) => u.user_id)).toEqual(["a", "d"]);
  });
});

describe("syncRolesDraft (admin user roles panel)", () => {
  it("keeps an unsaved edit when the user is refetched with the same roles", () => {
    // Coach unchecked, then the profile form saves and the user refetches.
    expect(syncRolesDraft("coach|parent", ["coach", "parent"], true, ["parent"])).toBeNull();
  });

  it("keeps an unsaved edit even when the stored roles change underneath it", () => {
    expect(syncRolesDraft("coach|parent", ["coach"], true, ["parent"])).toEqual({
      syncedKey: "coach",
      selected: ["parent"],
    });
  });

  it("follows the stored roles after a save or when nothing was edited", () => {
    expect(syncRolesDraft("coach|parent", ["parent"], false, ["coach", "parent"])).toEqual({
      syncedKey: "parent",
      selected: ["parent"],
    });
  });
});
