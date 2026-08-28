/**
 * Login-failure reason plumbing (issue #425).
 *
 * The backend attaches a machine-readable reason to auth 401s:
 * `{ error: { code: "Auth.NotAuthenticated", details: { reason: <code> } } }`.
 * Post-login and persona guards forward that reason to `/login?error=<code>`
 * so the login page can explain why sign-in bounced instead of showing an
 * empty form.
 */

import type { ApiError } from "@/lib/api/client";

/** Build the /login path for a failed auth check, carrying the reason code. */
export function loginPathForError(err: unknown): string {
  const reason = loginErrorCode(err);
  return reason ? `/login?error=${encodeURIComponent(reason)}` : "/login";
}

function loginErrorCode(err: unknown): string | null {
  if (typeof err !== "object" || err === null) return null;
  const apiErr = err as Partial<ApiError>;
  // Only auth-shaped failures carry a diagnosable reason; network errors and
  // timeouts (no status) fall back to a plain /login redirect.
  if (typeof apiErr.status !== "number") return null;
  const reason = apiErr.details?.reason;
  if (typeof reason === "string" && reason) return reason;
  if (typeof apiErr.code === "string" && apiErr.code) return apiErr.code;
  return null;
}

const MESSAGES: Record<string, string> = {
  "Identity.MembershipNotFound":
    "Your account isn't set up for this academy yet. Contact your academy to get access.",
  "Identity.UserNotFound":
    "We couldn't find an account for your email at this academy. Contact your academy to get set up.",
  "Identity.UserInactive":
    "Your account is currently inactive. Contact your academy for help.",
  "Identity.InvalidToken":
    "We couldn't verify your sign-in — your session may have expired or your email isn't verified yet. Please sign in again.",
  "Auth.TenantUnresolved":
    "We couldn't tell which academy you're signing in to. Please use your academy's own web address.",
};

const FALLBACK_MESSAGE =
  "We couldn't finish signing you in. Please try again, or contact your academy if this keeps happening.";

/** Map a `?error=<code>` value to a parent-friendly message. */
export function loginErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return MESSAGES[code] ?? FALLBACK_MESSAGE;
}
