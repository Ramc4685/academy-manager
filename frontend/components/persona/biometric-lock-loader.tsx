"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const BiometricLock = dynamic(
  () =>
    import("./biometric-lock").then(
      (m) => m.BiometricLock,
      () => {
        // Chunk failed (offline cold start, stale service worker): fail open, or the
        // pre-paint cover would hide the page with no lock screen and no way out.
        document.documentElement.removeAttribute("data-app-lock");
        return () => null;
      },
    ),
  { ssr: false },
);

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
