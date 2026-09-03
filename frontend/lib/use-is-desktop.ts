"use client";

import { useSyncExternalStore } from "react";

/**
 * Matches Tailwind's `lg:` breakpoint (64rem). Keep the two in sync: the
 * admin layout uses this hook to decide WHICH sidebar tree to mount, and
 * the sidebar's own `lg:` classes decide how it lays out. The query must
 * stay in rem: matchMedia resolves rem against the root font size exactly
 * as the CSS media query does, so a user who raises the browser's default
 * font size moves both thresholds together. A px query would diverge and
 * leave a viewport where the desktop sidebar is mounted but `hidden` while
 * the hamburger's drawer is never rendered.
 */
export const DESKTOP_QUERY = "(min-width: 64rem)";

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
