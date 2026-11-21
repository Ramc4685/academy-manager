/**
 * A family's referral code (L9 C2) carried from the academy page (`?ref=`)
 * through sign-up to the registration, where it is the only source that
 * counts on its own. Kept in localStorage on the academy host, which the
 * public page, sign-up and onboarding share; a blocked store just drops it.
 * A code older than 30 days is ignored, and it is removed once the
 * registration has saved it.
 */
const KEY = "courtmastr.referral_code";
const CODE = /^[A-Za-z0-9_.-]{1,80}$/;
export const REFERRAL_CODE_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

/** Remember `?ref=` from a landing URL; a later link with a code replaces it. */
export function captureReferralCode(search: string, now: number = Date.now()): void {
  const code = new URLSearchParams(search).get("ref")?.trim();
  if (!code || !CODE.test(code)) return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ code, at: now }));
  } catch {
    // Private mode or blocked storage: the referral is simply not carried.
  }
}

/** The remembered code, or "" when there is none or it is over 30 days old. */
export function storedReferralCode(now: number = Date.now()): string {
  try {
    const { code, at } = JSON.parse(window.localStorage.getItem(KEY) ?? "null") ?? {};
    const fresh = typeof at === "number" && now - at < REFERRAL_CODE_MAX_AGE_MS;
    return fresh && typeof code === "string" && CODE.test(code) ? code : "";
  } catch {
    return "";
  }
}

/** Forget the code: the registration saved it, or the parent removed it. */
export function clearReferralCode(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Blocked storage held nothing to clear.
  }
}
