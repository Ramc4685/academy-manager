/**
 * Maps payment/billing API failures to plain-language, parent-safe messages.
 *
 * Backend errors carry internal detail ("redirect url origin not allowed:
 * 'http://blno.localhost:3001'", Stripe customer ids, mandate codes...) that
 * must never be interpolated into a parent-facing banner. Modeled on
 * lib/auth/auth-error.ts: known error shapes map to friendly copy with a
 * recovery step, everything else falls back to the caller's generic message.
 * Raw backend detail is NEVER returned.
 */

export const BILLING_PORTAL_PREREQUISITE =
  "Billing portal is not set up yet. Start autopay for an enrollment first to get portal access.";

/** Stable backend error codes (DomainError.code via ApiError.code). */
const CODE_MESSAGES: Record<string, string> = {
  // Server-side redirect allowlist rejection — a configuration problem the
  // parent cannot fix; retrying will not help without academy support.
  InvalidRedirectUrl:
    "Something went wrong starting this payment step. Please try again or contact the academy.",
  // The academy's Stripe Connect account is not onboarded/enabled yet, so no
  // checkout of any kind can start. Seen on staging as a 502 with message
  // "Stripe connected account is not ready for autopay setup."
  "Billing.CheckoutCreationFailed":
    "Online payments aren't fully set up for your academy yet. Please try again later or contact the academy.",
};

/**
 * Known backend detail fragments that indicate the parent has no Stripe
 * customer / autopay setup yet — the one case where we can give a precise,
 * actionable next step instead of the generic fallback.
 */
const PORTAL_PREREQUISITE_PATTERNS = [/Stripe customer/i, /No such customer/i, /autopay setup/i];

function errorCode(err: unknown): string | undefined {
  if (err && typeof err === "object" && "code" in err) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return undefined;
}

function errorMessage(err: unknown): string {
  return err instanceof Error && typeof err.message === "string" ? err.message : "";
}

export function toPaymentErrorMessage(err: unknown, fallback: string): string {
  const code = errorCode(err);
  if (code && CODE_MESSAGES[code]) return CODE_MESSAGES[code];
  // Anything else is unknown backend detail — never show it to a parent.
  return fallback;
}

/**
 * Portal-open failures only: the "no Stripe customer yet" family of errors
 * means the parent must start autopay before a billing portal exists. That
 * hint is CORRECT for the portal button but circular for the autopay/pay
 * buttons (whose failures also mention "autopay setup"), so it lives in a
 * portal-specific mapper.
 */
export function toPortalErrorMessage(err: unknown, fallback: string): string {
  const code = errorCode(err);
  if (code && CODE_MESSAGES[code]) return CODE_MESSAGES[code];
  const message = errorMessage(err);
  if (message && PORTAL_PREREQUISITE_PATTERNS.some((p) => p.test(message))) {
    return BILLING_PORTAL_PREREQUISITE;
  }
  return fallback;
}
