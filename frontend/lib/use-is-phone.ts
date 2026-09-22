"use client";

import { useSyncExternalStore } from "react";

/**
 * Issue #847: every admin list was a desktop `<table>` wrapped in
 * `overflow-x-auto`. At 400px the status, the amount and the row actions all
 * sat off-screen behind a sideways scroll nobody discovers.
 *
 * The phone layout is chosen in JS rather than with `hidden md:block` /
 * `md:hidden` siblings on purpose: the two layouts describe the SAME rows and
 * therefore carry the SAME `data-testid`s, and a CSS-hidden twin would leave
 * two nodes per row in the DOM — a Playwright strict-mode violation in every
 * existing mobile spec that names a row. Mounting exactly one layout also
 * means the wide table is not merely invisible on a phone, it is not there at
 * all, so it cannot contribute scroll width.
 *
 * Matches Tailwind's `md:` breakpoint (48rem), and stays in rem for the same
 * reason `use-is-desktop.ts` does: matchMedia resolves rem against the root
 * font size exactly as the CSS media query does, so a reader who enlarges
 * their default font moves both thresholds together.
 */
export const PHONE_QUERY = "(max-width: 47.999rem)";

function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(PHONE_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return window.matchMedia(PHONE_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/**
 * True below the `md:` breakpoint. `false` on the server and during
 * hydration, so a list that gates its markup on this renders the table first
 * and swaps to phone rows once the client store is read — the rows themselves
 * only exist after the client query resolves, so nothing visible flips.
 */
export function useIsPhone(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
