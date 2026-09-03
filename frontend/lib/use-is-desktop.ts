"use client";

import { useSyncExternalStore } from "react";

/**
 * Matches Tailwind's `lg:` breakpoint (64rem). Keep the two in sync: the
 * admin layout uses this hook to decide WHICH sidebar tree to mount, and
 * the sidebar's own `lg:` classes decide how it lays out.
 */
const DESKTOP_QUERY = "(min-width: 1024px)";

function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(DESKTOP_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return window.matchMedia(DESKTOP_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/**
 * True when the viewport is at least the `lg:` breakpoint. `false` on the
 * server and during hydration, so a page that gates markup on it renders
 * the mobile tree first and switches once the client store is read.
 */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
