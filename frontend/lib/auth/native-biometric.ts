/**
 * Face ID / Touch ID / fingerprint lock inside the iOS/Android app shell.
 *
 * Opt-in per phone: the person turns it on from their profile, and from then on
 * the app asks for their face or fingerprint when it opens, and again when it
 * comes back after LOCK_AFTER_MS in the background. The phone passcode is the
 * fallback, so nobody is locked out by a failed scan. Sign-out turns it off, so
 * the next person on a shared phone starts clean.
 *
 * Browsers never reach the plugin: every entry point checks the shell first and
 * the plugin is dynamic-imported, so the web bundle loads no Capacitor code.
 * App builds without the plugin keep working and just never offer the lock.
 */

import { APP_LOCK_KEY } from "@/lib/auth/app-lock-key";
import { hasNativePlugin } from "@/lib/auth/native-sign-in";

const PLUGIN = "NativeBiometric";
/** Coming back sooner than this (a quick app switch) does not ask again. */
export const LOCK_AFTER_MS = 60_000;

// Mirrors the plugin's BiometryType enum; a local copy keeps it out of the web bundle.
const LABELS: Record<number, string> = {
  1: "Touch ID",
  2: "Face ID",
  3: "fingerprint",
  4: "face unlock",
  5: "iris unlock",
};

/** What to call the unlock method on this phone, e.g. "Face ID". */
export function biometricLabel(biometryType: number): string {
  return LABELS[biometryType] ?? "your phone's screen lock";
}

export function canUseBiometricLock(): boolean {
  return hasNativePlugin(PLUGIN);
}

export function isBiometricLockOn(): boolean {
  if (!canUseBiometricLock()) return false;
  try {
    return window.localStorage.getItem(APP_LOCK_KEY) === "1";
  } catch {
    return false;
  }
}

function saveSetting(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(APP_LOCK_KEY, "1");
    else window.localStorage.removeItem(APP_LOCK_KEY);
  } catch {
    // Storage blocked: the lock simply stays off.
  }
}

/**
 * The unlock label when this phone has a face, fingerprint or passcode set up,
 * otherwise null (nothing to offer).
 */
export async function biometricAvailability(): Promise<string | null> {
  if (!canUseBiometricLock()) return null;
  try {
    const { NativeBiometric } = await import("@capgo/capacitor-native-biometric");
    const result = await NativeBiometric.isAvailable({ useFallback: true });
    if (!result.isAvailable && !result.deviceIsSecure) return null;
    return biometricLabel(result.biometryType);
  } catch {
    return null;
  }
}

/** Ask for face/fingerprint (passcode as fallback). True when the person passed. */
export async function verifyWithBiometrics(reason: string): Promise<boolean> {
  try {
    const { NativeBiometric } = await import("@capgo/capacitor-native-biometric");
    await NativeBiometric.verifyIdentity({
      reason,
      title: "Unlock",
      negativeButtonText: "Cancel",
      useFallback: true,
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Hides the app-switcher snapshot while the lock is on. JS visibility events
 * fire too late for iOS's snapshot, so the native plugin covers the window.
 * Best effort: a build without the plugin just keeps the in-page cover.
 */
export function syncPrivacyScreen(on: boolean): void {
  if (!hasNativePlugin("PrivacyScreen")) return;
  void import("@capacitor-community/privacy-screen")
    .then(({ PrivacyScreen }) => (on ? PrivacyScreen.enable() : PrivacyScreen.disable()))
    .catch(() => {});
}

/** Turning it on asks once first, so nobody enables a lock their phone can't pass. */
export async function enableBiometricLock(): Promise<boolean> {
  const ok = await verifyWithBiometrics("Turn on app lock");
  if (ok) {
    saveSetting(true);
    syncPrivacyScreen(true);
  }
  return ok;
}

export function disableBiometricLock(): void {
  saveSetting(false);
  syncPrivacyScreen(false);
}
