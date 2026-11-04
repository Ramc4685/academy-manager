import { describe, expect, it } from "vitest";

import { assignableRoles, canManageUser } from "./assignable-roles";

describe("canManageUser (X3 mirror of ensure_can_manage_user)", () => {
  it("lets an owner manage anyone, including another owner", () => {
    expect(canManageUser(true, ["owner", "admin"])).toBe(true);
    expect(canManageUser(true, ["admin"])).toBe(true);
  });

  it("keeps a plain admin off owners and peer admins", () => {
    expect(canManageUser(false, ["owner"])).toBe(false);
    expect(canManageUser(false, ["admin"])).toBe(false);
    expect(canManageUser(false, ["parent", "admin"])).toBe(false);
  });

  it("lets a plain admin manage coaches, parents and staff tiers", () => {
    expect(canManageUser(false, ["coach", "parent"])).toBe(true);
    expect(canManageUser(false, ["billing"])).toBe(true);
    expect(canManageUser(false, ["front_desk"])).toBe(true);
  });
});

describe("assignableRoles", () => {
  it("never offers governance roles to a non-owner", () => {
    expect(assignableRoles(false)).not.toContain("admin");
    expect(assignableRoles(false)).not.toContain("owner");
  });
});
