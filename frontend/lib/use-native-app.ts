"use client";

import { useSyncExternalStore } from "react";

import { nativePlatform } from "@/lib/auth/native-sign-in";

const noSubscribe = () => () => {};

export const isNativeApp = (): boolean => nativePlatform() !== null;

/**
 * True inside the iOS/Android app shell, where a CSV download or
 * `window.print()` goes nowhere, so those actions are hidden there.
 * False on the server, so the first paint matches the web build.
 */
export function useIsNativeApp(): boolean {
  return useSyncExternalStore(noSubscribe, isNativeApp, () => false);
}
