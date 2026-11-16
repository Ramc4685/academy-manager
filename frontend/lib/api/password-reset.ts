import { apiFetch } from "./client";

/**
 * Ask the backend to email a branded set/reset-password link.
 *
 * Replaces Firebase's client `sendPasswordResetEmail`, whose shared
 * firebaseapp.com sender lands in spam. The backend always answers 204, known
 * address or not, so the caller shows one neutral message either way.
 */
export function requestPasswordReset(email: string): Promise<void> {
  return apiFetch<void>("/password-reset", {
    method: "POST",
    body: JSON.stringify({ email }),
    dedup: false,
  });
}
