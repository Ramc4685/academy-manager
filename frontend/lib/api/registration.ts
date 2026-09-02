import { apiFetch } from "./client";
import type { CurrentUser } from "./me";

export function registerPublicParent(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/register/parent", {
    method: "POST",
    body: "{}",
    dedup: false,
  });
}

/**
 * Sends the verification email from our own domain rather than Firebase's
 * shared default mailer, which was confirmed landing in spam. `authToken` is
 * passed explicitly because the caller signs the new user out immediately
 * after, so the ambient token may already be gone.
 */
export function sendParentVerificationEmail(authToken: string): Promise<void> {
  return apiFetch<void>("/register/parent/verification-email", {
    method: "POST",
    body: "{}",
    dedup: false,
    authToken,
  });
}
