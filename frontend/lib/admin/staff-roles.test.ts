import { describe, expect, it } from "vitest";

import type { AdminUserRole } from "@/lib/api/admin";
import { roleLabel } from "@/lib/admin/role-label";
import { ROLE_HINTS, planRoleChanges } from "@/lib/admin/staff-roles";
import { assignableRoles } from "@/lib/auth/assignable-roles";

describe("Staff page role assignment (#553, L2c)", () => {
  it("offers owners every staff role, including billing and front desk", () => {
    const roles = assignableRoles(true);
    for (const role of ["owner", "admin", "billing", "front_desk", "coach"] as const) {
      expect(roles).toContain(role);
    }
  });

  it("never offers an admin without owner a governance role", () => {
    const roles = assignableRoles(false);
    for (const role of ["owner", "admin", "billing", "front_desk"] as const) {
      expect(roles).not.toContain(role);
    }
    expect(roles).toEqual(["parent", "coach", "assistant_coach"]);
  });

  it("labels the staff tiers in plain words", () => {
    expect(roleLabel("billing")).toBe("Billing");
    expect(roleLabel("front_desk")).toBe("Front desk");
  });

  it("explains every role an owner can assign", () => {
    for (const role of assignableRoles(true)) {
      expect(ROLE_HINTS[role]).toMatch(/\S/);
    }
    expect(ROLE_HINTS.front_desk).toMatch(/never an amount/);
    expect(ROLE_HINTS.billing).toMatch(/No refunds or charges/);
  });

  it("grants before it revokes, so a swap never leaves the user roleless", () => {
    const plan = planRoleChanges(["admin"], ["billing"], assignableRoles(true));
    expect(plan).toEqual({ add: ["billing"], remove: ["admin"] });
  });

  it("sends nothing when the selection is unchanged", () => {
    expect(planRoleChanges(["coach", "billing"], ["billing", "coach"], assignableRoles(true))).toEqual(
      { add: [], remove: [] },
    );
  });

  it("never revokes a role the editor cannot toggle", () => {
    // An admin without owner edits a billing coach: billing is shown, not sent.
    const initial: AdminUserRole[] = ["coach", "billing"];
    const selected: AdminUserRole[] = ["coach", "parent"];
    const plan = planRoleChanges(initial, selected, assignableRoles(false));
    expect(plan).toEqual({ add: ["parent"], remove: [] });
  });

  it("revokes a staff tier for an owner", () => {
    const plan = planRoleChanges(["front_desk", "coach"], ["coach"], assignableRoles(true));
    expect(plan).toEqual({ add: [], remove: ["front_desk"] });
  });
});
