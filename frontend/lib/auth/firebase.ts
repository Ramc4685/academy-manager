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
  connectAuthEmulator,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  onAuthStateChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type User,
} from "firebase/auth";
import { shouldUseRedirectForGoogleSignIn } from "@/lib/auth/google-sign-in-mode";
import { getReadyIdToken } from "@/lib/auth/token-readiness";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

const firebaseAuthEmulatorHost = process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST ?? "";

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;
let _emulatorConnected = false;

function app(): FirebaseApp {
  if (_app) return _app;
  _app = getApps()[0] ?? initializeApp(firebaseConfig as Record<string, string>);
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

export async function registerWithEmail(email: string, password: string): Promise<User> {
  if (E2E_BYPASS) return fakeE2EUser(email);
  const { user } = await createUserWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function sendVerificationEmail(user: User): Promise<void> {
  if (E2E_BYPASS) {
    const failuresRemaining =
      typeof window === "undefined"
        ? 0
        : window.__E2E_FIREBASE__?.verificationFailuresRemaining ?? 0;
    if (failuresRemaining > 0 && window.__E2E_FIREBASE__) {
      window.__E2E_FIREBASE__.verificationFailuresRemaining = failuresRemaining - 1;
      throw new Error("E2E verification email failure");
    }
    return;
  }
  await sendEmailVerification(user);
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

export async function signInWithGoogle(): Promise<User | null> {
  const provider = googleProvider();
  if (shouldUseGoogleRedirect()) {
    await signInWithRedirect(auth(), provider);
    return null;
  }
  const { user } = await signInWithPopup(auth(), provider);
  return user;
}

export async function completeGoogleRedirectSignIn(): Promise<User | null> {
  if (E2E_BYPASS) return null;
  const result = await getRedirectResult(auth());
  return result?.user ?? null;
}

export async function sendPasswordReset(email: string): Promise<void> {
  await sendPasswordResetEmail(auth(), email);
}

export async function signOutCurrent(): Promise<void> {
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
