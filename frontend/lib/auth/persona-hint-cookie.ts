import {
  PERSONA_HINT_COOKIE,
  personaHintForRoles,
} from "@/lib/auth/persona-route-guard";

/**
 * The non-authoritative persona hint read by `middleware.ts` (#451).
 *
 * Deliberately *not* HttpOnly and `SameSite=Lax`, unlike the `__cm_identity`
 * bridge cookie: the edge must be able to read it, and it has to survive a
 * top-level navigation from an emailed link. It carries no token and no
 * personal data — only which persona shells the user may open — and the
 * backend still enforces the real check, so forging it buys nothing.
 *
 * Long-lived on purpose (30 days): Firebase sessions outlive the hourly
 * identity cookie, and an expired hint would bounce a still-signed-in user
 * to /login.
 */
const HINT_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export function setPersonaHintCookie(
  roles: readonly string[],
  hasPlatformAccess: boolean,
): void {
  if (typeof document === "undefined") return;
  const hint = personaHintForRoles(roles, hasPlatformAccess);
  if (!hint) {
    clearPersonaHintCookie();
    return;
  }
  document.cookie = `${PERSONA_HINT_COOKIE}=${hint}; ${hintCookieAttributes(
    HINT_MAX_AGE_SECONDS,
  )}`;
}

export function clearPersonaHintCookie(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${PERSONA_HINT_COOKIE}=; ${hintCookieAttributes(0)}`;
}

function hintCookieAttributes(maxAgeSeconds: number): string {
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  return `Path=/; SameSite=Lax; Max-Age=${maxAgeSeconds}${secure}`;
}
