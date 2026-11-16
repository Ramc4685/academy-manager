/**
 * A family's referral code (L9 C2) carried from the academy page (`?ref=`)
 * through sign-up to the registration, where it is the only source that
 * counts on its own. Kept in localStorage on the academy host, which the
 * public page, sign-up and onboarding share; a blocked store just drops it.
 */
const KEY = "courtmastr.referral_code";
const CODE = /^[A-Za-z0-9_.-]{1,80}$/;

/** Remember `?ref=` from a landing URL; a later link with a code replaces it. */
export function captureReferralCode(search: string): void {
  const code = new URLSearchParams(search).get("ref")?.trim();
  if (!code || !CODE.test(code)) return;
  try {
    window.localStorage.setItem(KEY, code);
  } catch {
    // Private mode or blocked storage: the referral is simply not carried.
  }
}

/** The remembered code, or "" when there is none. */
export function storedReferralCode(): string {
  try {
    const code = window.localStorage.getItem(KEY) ?? "";
    return CODE.test(code) ? code : "";
  } catch {
    return "";
  }
}
