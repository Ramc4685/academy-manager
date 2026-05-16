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
  getAuth,
  onAuthStateChanged,
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

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;

function app(): FirebaseApp {
  if (_app) return _app;
  _app = getApps()[0] ?? initializeApp(firebaseConfig as Record<string, string>);
  return _app;
}

export function auth(): Auth {
  if (_auth) return _auth;
  _auth = getAuth(app());
  return _auth;
}

export async function getIdToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const user = auth().currentUser;
  if (!user) return null;
  return user.getIdToken();
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  const { user } = await signInWithEmailAndPassword(auth(), email, password);
  return user;
}

export async function signInWithGoogle(): Promise<User> {
  const provider = new GoogleAuthProvider();
  const { user } = await signInWithPopup(auth(), provider);
  return user;
}

export async function signOutCurrent(): Promise<void> {
  await signOut(auth());
}

export function onAuthChange(cb: (user: User | null) => void): () => void {
  return onAuthStateChanged(auth(), cb);
}

export type { User };
