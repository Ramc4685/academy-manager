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
  onAuthStateChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";

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

export async function getIdToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  if (E2E_BYPASS) return "e2e-fake-token";
  const user = auth().currentUser;
  if (!user) return null;
  return user.getIdToken();
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  const { user } = await signInWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function registerWithEmail(email: string, password: string): Promise<User> {
  const { user } = await createUserWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function sendVerificationEmail(user: User): Promise<void> {
  await sendEmailVerification(user);
}

export async function signInWithGoogle(): Promise<User> {
  const provider = new GoogleAuthProvider();
  const { user } = await signInWithPopup(auth(), provider);
  return user;
}

export async function sendPasswordReset(email: string): Promise<void> {
  await sendPasswordResetEmail(auth(), email);
}

export async function signOutCurrent(): Promise<void> {
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
