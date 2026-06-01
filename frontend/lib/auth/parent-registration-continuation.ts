"use client";

const PENDING_PARENT_REGISTRATION_EMAIL = "am.pendingParentRegistrationEmail";

export function rememberPendingParentRegistration(email: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PENDING_PARENT_REGISTRATION_EMAIL, email.trim().toLowerCase());
}

export function consumePendingParentRegistration(email: string | null | undefined): boolean {
  if (typeof window === "undefined" || !email) return false;
  const pendingEmail = window.localStorage.getItem(PENDING_PARENT_REGISTRATION_EMAIL);
  return pendingEmail === email.trim().toLowerCase();
}

export function clearPendingParentRegistration(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PENDING_PARENT_REGISTRATION_EMAIL);
}
