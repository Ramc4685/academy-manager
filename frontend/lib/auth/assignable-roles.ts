import type { AdminUserRole } from "@/lib/api/admin";

/**
 * Roles the current user may grant from the admin surface. Owners may hand
 * out every academy role; admins without the owner scope may only manage the
 * operations roles — parents, coaches and assistant coaches — because the BFF
 * 403s an admin/owner grant from anyone else (`ensure_can_assign_role`), so
 * the UI does not offer it.
 */
export function assignableRoles(isOwner: boolean): AdminUserRole[] {
  return isOwner
    ? ["parent", "coach", "assistant_coach", "admin", "owner"]
    : ["parent", "coach", "assistant_coach"];
}
