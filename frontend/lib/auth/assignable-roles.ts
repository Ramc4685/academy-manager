import type { AdminUserRole } from "@/lib/api/admin";

/**
 * Roles the current user may grant from the admin surface. Owners may hand
 * out every academy role, including the staff money tiers `billing` and
 * `front_desk` (#553); admins without the owner scope may only manage the
 * operations roles — parents, coaches and assistant coaches — because the BFF
 * 403s an admin/owner/billing/front desk grant from anyone else
 * (`ensure_can_assign_role`), so the UI does not offer it.
 */
export function assignableRoles(isOwner: boolean): AdminUserRole[] {
  return isOwner
    ? ["parent", "coach", "assistant_coach", "front_desk", "billing", "admin", "owner"]
    : ["parent", "coach", "assistant_coach"];
}

/**
 * X3 mirror of the BFF's `ensure_can_manage_user`: an owner may change anyone;
 * an admin may only change users who hold neither `admin` nor `owner`. Covers
 * the profile (email, status), roles and set-password invite controls. The
 * BFF also lets anyone edit their own profile; this page does not know the
 * viewer's id, so a plain admin sees their own page read-only (stricter, never
 * looser). The BFF 403 is the boundary; this only hides what would fail.
 */
export function canManageUser(
  isOwner: boolean,
  targetRoles: readonly AdminUserRole[],
): boolean {
  return isOwner || !targetRoles.some((role) => role === "admin" || role === "owner");
}
