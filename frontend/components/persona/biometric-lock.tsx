"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ds/button";
import { brand } from "@/lib/brand";
import {
  LOCK_AFTER_MS,
  isBiometricLockOn,
  syncPrivacyScreen,
  verifyWithBiometrics,
} from "@/lib/auth/native-biometric";

/**
 * Covers the app until the person passes Face ID / fingerprint, when they
 * turned app lock on (see lib/auth/native-biometric.ts). Mounted once at the
 * root through BiometricLockLoader, so it only ever loads inside the app shell.
 */
export function BiometricLock() {
  const [covered, setCovered] = useState(false);
  const [busy, setBusy] = useState(false);
  const needsUnlock = useRef(false);
  const busyRef = useRef(false);
  const hiddenAt = useRef<number | null>(null);

  const unlock = useCallback(async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    const ok = await verifyWithBiometrics(`Unlock ${brand.productName}`);
    busyRef.current = false;
    setBusy(false);
    if (ok) {
      needsUnlock.current = false;
      setCovered(false);
      document.documentElement.removeAttribute("data-app-lock");
    }
  }, []);

  useEffect(() => {
    // The native cover resets on every launch (config enable:false).
    syncPrivacyScreen(isBiometricLockOn());
    if (isBiometricLockOn()) {
      needsUnlock.current = true;
      setCovered(true);
      void unlock();
    } else {
      // Setting gone (e.g. signed out in another tab): drop the pre-paint cover.
      document.documentElement.removeAttribute("data-app-lock");
    }

    function onVisibility() {
      // The system prompt can itself background the web view on some phones.
      if (busyRef.current || !isBiometricLockOn()) return;
      if (document.visibilityState === "hidden") {
        hiddenAt.current = Date.now();
        // Cover right away so the app switcher snapshot shows no family data, and
        // hide the page behind it from screen readers and focus (the CSS rule).
        document.documentElement.setAttribute("data-app-lock", "");
        setCovered(true);
        return;
      }
      const away = hiddenAt.current === null ? 0 : Date.now() - hiddenAt.current;
      hiddenAt.current = null;
      // A clock set backwards (negative away) locks too.
      if (away >= LOCK_AFTER_MS || away < 0) needsUnlock.current = true;
      if (needsUnlock.current) void unlock();
      else {
        document.documentElement.removeAttribute("data-app-lock");
        setCovered(false);
      }
    }

    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [unlock]);

  // Same clean-up as the profile's Log out button, minus the in-memory query
  // cache, which the full page load below drops anyway.
  async function signOut() {
    const [{ signOutCurrent }, { clearDeviceData, unsentMarkCount }, { clearPersistedQueryCache }] =
      await Promise.all([
        import("@/lib/auth/firebase"),
        import("@/components/persona/logout-button"),
        import("@/lib/query/persistence"),
      ]);
    const unsent = await unsentMarkCount();
    if (
      unsent > 0 &&
      !window.confirm(
        `${unsent} attendance ${unsent === 1 ? "mark hasn't" : "marks haven't"} been sent yet. ` +
          "Signing out deletes them from this phone. Sign out anyway?",
      )
    ) {
      return;
    }
    try {
      await signOutCurrent();
      await clearDeviceData();
      clearPersistedQueryCache();
    } finally {
      // Even if clean-up failed, leave the lock screen rather than look stuck.
      window.location.replace("/login");
    }
  }

  if (!covered) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="app-lock-title"
      data-testid="app-lock"
      data-app-lock-cover=""
      className="fixed inset-0 z-[1000] flex flex-col items-center justify-center gap-4 bg-rally-paper px-6 text-center"
    >
      <h1 id="app-lock-title" className="text-xl font-semibold text-rally-ink">
        {brand.productName} is locked
      </h1>
      <p className="max-w-xs text-sm text-rally-muted">
        Use your face, fingerprint or phone passcode to continue.
      </p>
      <Button variant="primary" size="lg" autoFocus onClick={() => void unlock()} disabled={busy}>
        {busy ? "Waiting…" : "Unlock"}
      </Button>
      <button
        type="button"
        onClick={() => void signOut()}
        className="min-h-touch px-4 text-sm font-medium text-rally-muted underline"
      >
        Sign out instead
      </button>
    </div>
  );
}
