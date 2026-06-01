import { apiFetch } from "./client";

export type UserRole = "admin" | "coach" | "parent";

export interface CurrentUser {
  user_id: string;
  email: string;
  academy_id: string;
  roles: UserRole[];
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
