/**
 * Maps Firebase auth failures to plain-language, user-safe messages.
 *
 * Firebase throws errors whose `.message` looks like
 * `Firebase: Error (auth/wrong-password).` — rendering that directly leaks the
 * provider name and a cryptic code, and tells the user nothing useful. This
 * helper turns the stable `.code` into friendly copy with a recovery step, and
 * never lets raw provider text reach the UI.
 *
 * Unknown codes (and non-Firebase errors) fall back to the caller's message.
 * Our own thrown Errors that carry an already-safe message (no `Firebase:`
 * prefix, no `(auth/...)` code) are passed through unchanged.
 */

const CODE_MESSAGES: Record<string, string> = {
  // Sign-in credential failures are intentionally merged so we never reveal
  // whether the email or the password was the wrong one.
  "auth/invalid-credential": "Email or password is incorrect. Check your details and try again.",
  "auth/invalid-login-credentials": "Email or password is incorrect. Check your details and try again.",
  "auth/wrong-password": "Email or password is incorrect. Check your details and try again.",
  "auth/user-not-found": "Email or password is incorrect. Check your details and try again.",
  "auth/invalid-email": "That email address does not look right. Check it and try again.",
  "auth/missing-password": "Enter your password and try again.",
  "auth/user-disabled": "This account has been disabled. Contact your academy for help.",
  "auth/too-many-requests": "Too many attempts. Wait a few minutes, then try again.",
  "auth/network-request-failed": "We could not reach the network. Check your connection and try again.",
  "auth/email-already-in-use": "An account already exists for this email. Sign in instead.",
  "auth/weak-password": "Choose a stronger password — at least 8 characters.",
  "auth/account-exists-with-different-credential":
    "An account already exists for this email using a different sign-in method. Try that method instead.",
  "auth/popup-closed-by-user": "Sign-in was cancelled. Try again when you are ready.",
  "auth/cancelled-popup-request": "Sign-in was cancelled. Try again when you are ready.",
  "auth/popup-blocked": "Your browser blocked the sign-in window. Allow pop-ups for this site and try again.",
  "auth/requires-recent-login": "For your security, please sign in again to continue.",
  "auth/operation-not-allowed": "This sign-in method is not available right now. Try another option.",
};

function errorCode(err: unknown): string | undefined {
  if (err && typeof err === "object" && "code" in err) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string") return code;
  }
  return undefined;
}

/**
 * Returns true when an error message is raw Firebase output that must never be
 * shown to a user (mentions the provider or carries an `(auth/...)` code).
 */
function looksLikeRawProviderText(message: string): boolean {
  return /firebase/i.test(message) || /\(auth\//.test(message);
}

export function toAuthErrorMessage(err: unknown, fallback: string): string {
  const code = errorCode(err);
  if (code) {
    return CODE_MESSAGES[code] ?? fallback;
  }
  // Non-Firebase Error with an already-safe, curated message — keep it.
  if (err instanceof Error && err.message && !looksLikeRawProviderText(err.message)) {
    return err.message;
  }
  return fallback;
}
