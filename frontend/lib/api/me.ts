import { apiFetch } from "./client";

export type UserRole = "admin" | "coach" | "parent";

/**
 * Cross-tenant capabilities. Deliberately separate from `UserRole`: the
 * backend keeps these out of `roles` so a tenant admin can never satisfy a
 * platform check (see backend/v2/shared/auth/claims.py).
 */
export type PlatformRole = "platform_admin" | "platform_support";

export interface CurrentUser {
  user_id: string;
  email: string;
  academy_id: string;
  roles: UserRole[];
  /** Absent for every ordinary tenant user. */
  platform_roles?: PlatformRole[];
}

export function isPlatformAdmin(user: CurrentUser): boolean {
  return (user.platform_roles ?? []).includes("platform_admin");
}

/** Any platform capability — admin or read-only support. */
export function hasPlatformAccess(user: CurrentUser): boolean {
  return (user.platform_roles ?? []).length > 0;
}

export type RoleHome = "/admin" | "/coach/today" | "/parent/payments" | "/login";

export function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/me", { method: "GET", dedup: false });
}

export function getCurrentUserWithToken(authToken: string): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/me", { method: "GET", dedup: false, authToken });
}

export function homeForRoles(roles: UserRole[]): RoleHome {
  if (roles.includes("admin")) return "/admin";
  if (roles.includes("coach")) return "/coach/today";
  if (roles.includes("parent")) return "/parent/payments";
  return "/login";
}
