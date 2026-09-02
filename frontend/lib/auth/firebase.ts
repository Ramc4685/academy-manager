"use client";

/**
 * Modular Firebase auth — only the pieces we use, no full SDK import.
 *
 * Per ADR-0001 (modular imports) and ADR-0004 (PWA-friendly auth).
 */

import { FirebaseApp, getApps, initializeApp } from "firebase/app";
import {
  Auth,
  GoogleAuthProvider,
  confirmPasswordReset,
  connectAuthEmulator,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithCustomToken,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  verifyPasswordResetCode,
  type User,
} from "firebase/auth";
import { resolveAuthDomain } from "@/lib/auth/auth-domain";
import { shouldUseRedirectForGoogleSignIn } from "@/lib/auth/google-sign-in-mode";
import { getReadyIdToken } from "@/lib/auth/token-readiness";
import { clearBffIdentityCookie } from "@/lib/api/auth-bridge-cookie";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

const firebaseAuthEmulatorHost = process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST ?? "";
const authProxyEnabled = process.env.NEXT_PUBLIC_FIREBASE_AUTH_PROXY === "1";

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;
let _emulatorConnected = false;

function app(): FirebaseApp {
  if (_app) return _app;
  const existing = getApps()[0];
  if (existing) {
    _app = existing;
    return _app;
  }
  const authDomain = resolveAuthDomain({
    configuredAuthDomain: firebaseConfig.authDomain,
    proxyEnabled: authProxyEnabled,
    pageHost: typeof window === "undefined" ? undefined : window.location.host,
  });
  _app = initializeApp({ ...firebaseConfig, authDomain } as Record<string, string>);
  return _app;
}

export function auth(): Auth {
  if (_auth) return _auth;
  _auth = getAuth(app());
  if (firebaseAuthEmulatorHost && !_emulatorConnected) {
    connectAuthEmulator(_auth, firebaseAuthEmulatorHost, { disableWarnings: true });
    _emulatorConnected = true;
  }
  return _auth;
}

const E2E_BYPASS = process.env.NEXT_PUBLIC_E2E_AUTH_BYPASS === "1";

declare global {
  interface Window {
    __E2E_FIREBASE__?: {
      verificationFailuresRemaining?: number;
    };
  }
}

function fakeE2EUser(email: string, emailVerified = false): User {
  return {
    uid: "e2e-parent",
    email,
    emailVerified,
    getIdToken: async () => "e2e-fake-token",
  } as unknown as User;
}

export async function getIdToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  if (E2E_BYPASS) return "e2e-fake-token";
  const firebaseAuth = auth();
  return getReadyIdToken(firebaseAuth, (callback) =>
    onAuthStateChanged(firebaseAuth, callback)
  );
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  if (E2E_BYPASS) return fakeE2EUser(email, true);
  const { user } = await signInWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function signInWithCustomTokenValue(token: string): Promise<User> {
  if (E2E_BYPASS) return fakeE2EUser("magic@example.com", true);
  const { user } = await signInWithCustomToken(auth(), token);
  return user;
}

export async function registerWithEmail(email: string, password: string): Promise<User> {
  if (E2E_BYPASS) return fakeE2EUser(email);
  const { user } = await createUserWithEmailAndPassword(auth(), email, password);
  return user;
}

/**
 * Verification email is sent by the backend (Admin SDK generates the Firebase
 * link, our Resend domain delivers it), not by Firebase's client-side
 * `sendEmailVerification` — that shared unbranded sender was confirmed landing
 * in spam in production. This helper only yields the token the caller needs to
 * authenticate that backend call; see `sendParentVerificationEmail`. It lives
 * here rather than calling the API directly because `lib/api/client` imports
 * this module, so the reverse import would be circular.
 *
 * Always resolves to a usable token or throws. It must never resolve to null:
 * the caller's only signal that the send failed is an exception, so a nullish
 * return would let a "no token" case fall straight through to the success
 * branch and tell the parent an email was sent that nothing ever attempted.
 */
export async function verificationRequestToken(user: User): Promise<string> {
  if (E2E_BYPASS) {
    const failuresRemaining =
      typeof window === "undefined"
        ? 0
        : window.__E2E_FIREBASE__?.verificationFailuresRemaining ?? 0;
    if (failuresRemaining > 0 && window.__E2E_FIREBASE__) {
      window.__E2E_FIREBASE__.verificationFailuresRemaining = failuresRemaining - 1;
      throw new Error("E2E verification email failure");
    }
    // Same placeholder `getIdToken` hands out under the bypass. Returning a
    // token (rather than null) is what keeps the e2e run on the real code
    // path: the API call is still made, so the spec can assert it happened.
    return "e2e-fake-token";
  }
  const token = await user.getIdToken();
  if (!token) throw new Error("Could not obtain an auth token for the verification email");
  return token;
}

function googleProvider(): GoogleAuthProvider {
  const provider = new GoogleAuthProvider();
  provider.addScope("profile");
  provider.addScope("email");
  return provider;
}

function shouldUseGoogleRedirect(): boolean {
  if (typeof navigator === "undefined") return false;
  return shouldUseRedirectForGoogleSignIn({
    userAgent: navigator.userAgent,
    maxTouchPoints: navigator.maxTouchPoints ?? 0,
    platform: navigator.platform,
  });
}

// Marks that this tab left for a Google redirect sign-in, so the return
// trip can tell "nothing happened" apart from "the redirect came back
// empty". getRedirectResult() resolving null after a real redirect is how
// blocked third-party storage manifests — without the marker it is a
// silent bounce back to /login with no error for the user or for us.
const GOOGLE_REDIRECT_PENDING_KEY = "am.googleRedirectPending";

function markGoogleRedirectPending(): void {
  try {
    window.sessionStorage.setItem(GOOGLE_REDIRECT_PENDING_KEY, "1");
  } catch {
    // Storage unavailable — lose the diagnostic, not the sign-in.
  }
}

function consumeGoogleRedirectPending(): boolean {
  try {
    const pending =
      window.sessionStorage.getItem(GOOGLE_REDIRECT_PENDING_KEY) === "1";
    window.sessionStorage.removeItem(GOOGLE_REDIRECT_PENDING_KEY);
    return pending;
  } catch {
    return false;
  }
}

export async function signInWithGoogle(): Promise<User | null> {
  const provider = googleProvider();
  if (shouldUseGoogleRedirect()) {
    markGoogleRedirectPending();
    if (E2E_BYPASS) {
      const url = new URL("/__/auth/handler", window.location.origin);
      url.searchParams.set("authType", "signInViaRedirect");
      url.searchParams.set("providerId", "google.com");
      window.location.assign(url.toString());
      return null;
    }
    await signInWithRedirect(auth(), provider);
    return null;
  }
  if (E2E_BYPASS) return fakeE2EUser("google@example.com", true);
  const { user } = await signInWithPopup(auth(), provider);
  return user;
}

export async function completeGoogleRedirectSignIn(): Promise<User | null> {
  if (E2E_BYPASS) return null;
  const wasPending = consumeGoogleRedirectPending();
  const result = await getRedirectResult(auth());
  if (result?.user) return result.user;
  if (wasPending) {
    throw new Error(
      "Google sign-in could not complete on this browser. Please try again, or sign in with your email and password."
    );
  }
  return null;
}

export async function sendPasswordReset(email: string): Promise<void> {
  await sendPasswordResetEmail(auth(), email);
}

/**
 * Validate a password-reset `oobCode` and return the email it belongs to.
 *
 * Throws for an expired, already-used, or malformed code, which is how
 * `/auth/action` tells those states apart before showing a password form.
 */
export async function verifyPasswordResetCodeValue(oobCode: string): Promise<string> {
  if (E2E_BYPASS) return "e2e-parent@example.com";
  return verifyPasswordResetCode(auth(), oobCode);
}

/**
 * Complete a password reset.
 *
 * This hits the same Identity Toolkit `accounts:resetPassword` endpoint as
 * Firebase's own hosted action page, so it keeps that endpoint's side effect of
 * marking the account's email verified — redeeming the code proves the parent
 * controls the mailbox. That side effect is load-bearing: password sign-in is
 * rejected without it by `_require_verified_password_provider_email` in
 * `backend/v2/contexts/identity/application/use_cases/load_auth_claims.py`.
 * Do not swap this for a custom reset endpoint without re-verifying that.
 */
export async function confirmPasswordResetValue(
  oobCode: string,
  newPassword: string
): Promise<void> {
  if (E2E_BYPASS) return;
  await confirmPasswordReset(auth(), oobCode, newPassword);
}

export async function signOutCurrent(): Promise<void> {
  clearBffIdentityCookie();
  if (E2E_BYPASS) return;
  await signOut(auth());
}

export function onAuthChange(cb: (user: User | null) => void): () => void {
  if (E2E_BYPASS) {
    // E2E mode: synthesise a logged-in fake user immediately. Returns a
    // no-op unsubscribe so the layout's useEffect cleanup works.
    const fakeUser = {
      uid: "e2e-coach",
      email: "coach@example.com",
      getIdToken: async () => "e2e-fake-token",
    } as unknown as User;
    queueMicrotask(() => cb(fakeUser));
    return () => undefined;
  }
  return onAuthStateChanged(auth(), cb);
}

export type { User };
