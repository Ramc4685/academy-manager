import { apiFetch } from "./client";

export type UserRole = "admin" | "coach" | "parent";

export interface CurrentUser {
  user_id: string;
  email: string;
  academy_id: string;
  roles: UserRole[];
}

export type RoleHome = "/admin" | "/coach/dashboard" | "/parent/dashboard" | "/login";

export function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/me", { method: "GET", dedup: false });
}

export function homeForRoles(roles: UserRole[]): RoleHome {
  if (roles.includes("admin")) return "/admin";
  if (roles.includes("coach")) return "/coach/dashboard";
  if (roles.includes("parent")) return "/parent/dashboard";
  return "/login";
}
