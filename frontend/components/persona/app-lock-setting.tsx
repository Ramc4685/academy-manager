"use client";

import { useEffect, useState } from "react";

import {
  biometricAvailability,
  disableBiometricLock,
  enableBiometricLock,
  isBiometricLockOn,
  verifyWithBiometrics,
} from "@/lib/auth/native-biometric";

/**
 * Profile switch for the app lock. Renders nothing in a browser, in an app
 * build without the plugin, or on a phone with no face, fingerprint or passcode.
 */
export function AppLockSetting() {
  const [label, setLabel] = useState<string | null>(null);
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void biometricAvailability().then((found) => {
      setLabel(found);
      setOn(isBiometricLockOn());
    });
  }, []);

  if (!label) return null;

  async function toggle() {
    if (busy) return;
    setError(null);
    setBusy(true);
    if (on) {
      // Same check as turning it on, so whoever holds an unlocked phone can't drop the lock.
      const ok = await verifyWithBiometrics("Turn off app lock");
      setBusy(false);
      if (ok) {
        disableBiometricLock();
        setOn(false);
      } else setError(`${label} didn't confirm, so app lock is still on.`);
      return;
    }
    const ok = await enableBiometricLock();
    setBusy(false);
    if (ok) setOn(true);
    else setError(`${label} didn't confirm, so app lock is still off.`);
  }

  return (
    <section
      data-testid="app-lock-setting"
      className="rounded-2xl border border-rally-line bg-white p-4"
    >
      <label className="flex min-h-11 items-center justify-between gap-4">
        <span>
          <span className="block font-semibold text-rally-ink">Lock with {label}</span>
          <span className="mt-1 block text-sm text-rally-muted">
            Ask for {label} when the app opens or after a minute away. Only on this phone.
          </span>
        </span>
        <input
          type="checkbox"
          role="switch"
          data-testid="app-lock-switch"
          checked={on}
          disabled={busy}
          onChange={() => void toggle()}
          className="size-5 shrink-0 accent-blue-600"
        />
      </label>
      {error && <p className="mt-2 text-sm text-status-red-800">{error}</p>}
    </section>
  );
}
