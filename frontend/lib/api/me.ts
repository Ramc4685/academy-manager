import { apiFetch } from "./client";

export type UserRole =
  | "admin"
  | "coach"
  | "assistant_coach"
  | "parent"
  | "student"
  | "owner";

/**
 * Roles that have their own persona shell and home route. `owner` is a
 * franchise scope reached from the tenant switcher, not a persona view, and
 * `assistant_coach` rides the coach shell (scoped to its assigned sessions)
 * rather than owning one.
 */
export type PersonaRole = Exclude<UserRole, "owner" | "assistant_coach">;

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

export {
  COACH_SUPERVISOR_ROLES,
  COACH_SURFACE_ROLES,
  availablePersonaViews,
  canSuperviseCoaching,
  isAssistantCoach,
} from "@/lib/auth/coach-supervisor";

export function isPlatformAdmin(user: CurrentUser): boolean {
  return (user.platform_roles ?? []).includes("platform_admin");
}

/** Any platform capability — admin or read-only support. */
export function hasPlatformAccess(user: CurrentUser): boolean {
  return (user.platform_roles ?? []).length > 0;
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
  // Assistants land on the same shell as coaches; the shell scopes what they
  // see to the sessions they are listed on.
  if (roles.includes("assistant_coach")) return "/coach/today";
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
