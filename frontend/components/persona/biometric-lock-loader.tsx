"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const BiometricLock = dynamic(
  () => import("./biometric-lock").then((m) => m.BiometricLock),
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
