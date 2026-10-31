import type { AdminUserRole, ListAdminUsersOptions } from "@/lib/api/admin";

/**
 * Sidebar regroup PR 3: `/admin/users` is the Staff list. Parents left it for
 * Families, so the pills are staff roles only and the unfiltered view asks the
 * BFF to drop parent-only accounts (`exclude_role=parent`, #918). A coach who
 * is also a parent still appears, because the exclusion is on accounts whose
 * only role is parent.
 */
export type StaffRoleFilter = Extract<AdminUserRole, "coach" | "assistant_coach" | "admin">;

export const STAFF_ROLE_FILTERS: ReadonlyArray<{
  label: string;
  value: StaffRoleFilter | undefined;
}> = [
  { label: "All staff", value: undefined },
  { label: "Coaches", value: "coach" },
  { label: "Assistant coaches", value: "assistant_coach" },
  { label: "Admins", value: "admin" },
];

/**
 * `?role=parent` is still a working page: browsers that cached the old 308
 * from `/admin/parents` keep landing here, and it is the only list of parents
 * with no children yet (spec §3.1, §3.3). It lists parents and shows a banner
 * pointing at Families instead of a selected pill.
 */
export function parseRoleParam(value: string | null): AdminUserRole | undefined {
  return value === "coach" ||
    value === "assistant_coach" ||
    value === "parent" ||
    value === "admin"
    ? value
    : undefined;
}

/** Options for `listAdminUsers(role, ...)` given the active pill. */
export function staffListOptions(role: AdminUserRole | undefined): ListAdminUsersOptions {
  return role ? {} : { excludeRole: "parent" };
}

/**
 * Query-key segment for the directory read. "All staff" is NOT the same
 * payload as the unfiltered `listAdminUsers()` other screens cache under
 * `queryKeys.admin.users()` (People search, the roles panel), so it must not
 * share that key.
 */
export function staffQueryRole(role: AdminUserRole | undefined): string {
  return role ?? "staff";
}
