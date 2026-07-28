import { apiFetch } from "./client";

export type UserRole = "admin" | "coach" | "parent" | "student" | "owner";

/**
 * Roles that have their own persona shell and home route. `owner` is a
 * franchise scope reached from the tenant switcher, not a persona view.
 */
export type PersonaRole = Exclude<UserRole, "owner">;

export interface CurrentUser {
  user_id: string;
  email: string;
  academy_id: string;
  roles: UserRole[];
}

export type RoleHome =
  | "/admin"
  | "/coach/today"
  | "/parent/payments"
  | "/student/dashboard"
  | "/owner"
  | "/login";

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
  // A user can hold both "parent" and "student" (UIM12 allows this by
  // design — persona routing follows the requested BFF, not an exclusive
  // account type). Parent wins when both are present since it's the richer,
  // pre-existing surface; "student" is the fallback for student-only logins.
  if (roles.includes("student")) return "/student/dashboard";
  // Owner is a scope, not a persona shell, so it ranks last — but an
  // owner-only user still needs somewhere to land.
  if (roles.includes("owner")) return "/owner";
  return "/login";
}
