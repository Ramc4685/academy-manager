"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const BiometricLock = dynamic(
  () =>
    import("./biometric-lock").then(
      (m) => m.BiometricLock,
      // Chunk failed (offline cold start, stale service worker): stay locked, but
      // never as a blank screen with no way out.
      () => LockUnavailable,
    ),
  { ssr: false },
);

/** Bundled with the loader, so it shows even when the lock chunk cannot load. */
function LockUnavailable() {
  // The pre-paint cover is set only when the lock is on; otherwise nothing to hold.
  if (!document.documentElement.hasAttribute("data-app-lock")) return null;
  return (
    <div
      role="alert"
      data-app-lock-cover=""
      className="fixed inset-0 z-[1000] flex flex-col items-center justify-center gap-4 bg-rally-paper px-6 text-center"
    >
      <p className="max-w-xs text-sm text-rally-muted">
        App lock couldn&apos;t load. Check your connection and try again.
      </p>
      <button
        type="button"
        autoFocus
        onClick={() => window.location.reload()}
        className="min-h-touch rounded-lg bg-rally-ink px-5 text-sm font-semibold text-white"
      >
        Reload
      </button>
    </div>
  );
}

/**
 * Loads the app lock only inside the iOS/Android shell, so browsers (and the
 * marketing pages) never download it or the Firebase code it pulls in.
 */
export function BiometricLockLoader() {
  const [inApp, setInApp] = useState(false);
  useEffect(() => {
    const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor;
    setInApp(cap?.isNativePlatform?.() === true);
  }, []);
  return inApp ? <BiometricLock /> : null;
}
