import type { AdminUserRole } from "@/lib/api/admin";

/** The roles that make a user a coach for pay-rate and session-assignment purposes. */
export const COACH_ROLES: ReadonlyArray<AdminUserRole> = ["coach", "assistant_coach"];

/**
 * Whether a user holds a coaching role on any of their roles, not only the
 * primary one. The user detail page used to gate the pay-rate and sessions
 * panels on `user.role === "coach"`, so a parent who also coaches (primary
 * role `parent`, `roles` containing `coach`) or an assistant coach never saw
 * either panel and could not be paid or assigned from their own page.
 */
export function hasCoachRole(user: {
  role: AdminUserRole | string;
  roles?: ReadonlyArray<AdminUserRole | string> | null;
}): boolean {
  const roles = user.roles && user.roles.length > 0 ? user.roles : [user.role];
  return roles.some((r) => (COACH_ROLES as ReadonlyArray<string>).includes(r));
}
