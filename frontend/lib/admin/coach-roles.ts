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

/**
 * Coaches who may be given a class: active accounts only. A disabled or
 * inactive coach cannot sign in to run it. ``keepId`` (the coach already on
 * the class) stays listed so the select can still show the current value.
 */
export function assignableCoaches<T extends { user_id: string; status: string }>(
  users: ReadonlyArray<T>,
  keepId?: string | null,
): T[] {
  return users.filter((user) => user.status === "active" || user.user_id === keepId);
}
