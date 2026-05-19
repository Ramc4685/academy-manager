import { apiFetch } from "./client";
import type { CurrentUser } from "./me";

export function registerPublicParent(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/register/parent", {
    method: "POST",
    body: "{}",
    dedup: false,
  });
}
