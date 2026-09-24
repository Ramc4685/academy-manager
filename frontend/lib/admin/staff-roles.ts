import type { AdminUserRole } from "@/lib/api/admin";

/**
 * Staff page role assignment (#553, roadmap L2c).
 *
 * One line per role saying what it can do, shown next to the checkboxes so
 * the owner picks a tier knowing what it grants. The wording follows the
 * owner decision of 2026-09-22 (roadmap section 6 item 2): billing sees
 * amounts and records payments a family already made; front desk sees an
 * "owes money" flag only; every money-moving action stays with the owner.
 */
export const ROLE_HINTS: Readonly<Record<AdminUserRole, string>> = {
  owner: "Every money action, and grants or revokes every role.",
  admin: "Runs classes, families and schedules. Sees balances and records payments.",
  billing: "Sees amounts and records payments a family already made. No refunds or charges.",
  front_desk: "Sees an \"owes money\" flag only, never an amount. No money actions.",
  coach: "Teaches assigned classes and takes attendance.",
  assistant_coach: "Helps on assigned classes and takes attendance.",
  parent: "Signs in to see their own children and invoices.",
};

export interface RoleChangePlan {
  add: AdminUserRole[];
  remove: AdminUserRole[];
}

/**
 * The role grants and revocations a Save sends, in order.
 *
 * Only roles this editor may toggle (`editable`) are ever sent: an admin
 * without owner never revokes a role they could not grant. Grants go first so
 * a swap (admin -> billing) never passes through "no roles at all", which the
 * store refuses. Order follows `editable`, so the requests are deterministic.
 */
export function planRoleChanges(
  initial: ReadonlyArray<AdminUserRole>,
  selected: ReadonlyArray<AdminUserRole>,
  editable: ReadonlyArray<AdminUserRole>,
): RoleChangePlan {
  const before = new Set(initial);
  const after = new Set(selected);
  return {
    add: editable.filter((role) => after.has(role) && !before.has(role)),
    remove: editable.filter((role) => before.has(role) && !after.has(role)),
  };
}

