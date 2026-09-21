"use client";

import { useEffect, useState } from "react";

/**
 * Remembers a section's collapsed/open state per device (#859 remainder).
 *
 * The session detail page's three context cards (Coaching staff, Class
 * dates, Communication pack) used to hold their open/closed state in a
 * plain `useState(true)`, so an admin who collapsed one to focus on the
 * roster had it reopen on every navigation back to the page.
 *
 * Backed by `localStorage`, keyed by a fixed string per section — a device
 * preference, not a per-session one, matching "remember ... per device": an
 * admin who always keeps Class dates closed wants that everywhere, not only
 * on the one session they were viewing when they closed it.
 *
 * Reads and writes are wrapped in try/catch and default open (`true`) on any
 * failure — private browsing, disabled storage, or a value that doesn't
 * parse as a boolean — the same guard `use-is-phone.ts` applies to its own
 * browser API. The initial render always returns the default so the server
 * and the first client paint match; the persisted value (if any) is applied
 * in an effect right after mount, same as `use-is-phone.ts`'s `false` first
 * paint.
 */
function readStored(key: string): boolean | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === "true") return true;
    if (raw === "false") return false;
    return null;
  } catch {
    return null;
  }
}

function writeStored(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? "true" : "false");
  } catch {
    // Private browsing / disabled storage: the preference just doesn't
    // survive this device. Nothing else in the page depends on it.
  }
}

/**
 * `key` should be a fixed, section-specific string (e.g.
 * `"admin.session-detail.staffOpen"`), not derived from a session id — the
 * preference is meant to follow the admin across every session they open.
 */
export function usePersistedOpen(key: string, defaultOpen = true): [boolean, (value: boolean | ((current: boolean) => boolean)) => void] {
  const [open, setOpenState] = useState(defaultOpen);

  useEffect(() => {
    const stored = readStored(key);
    if (stored !== null) setOpenState(stored);
    // Only re-reads when `key` itself changes: a later external change to
    // localStorage (another tab) is not something this page needs to react
    // to live.
  }, [key]);

  const setOpen = (value: boolean | ((current: boolean) => boolean)): void => {
    setOpenState((current) => {
      const next = typeof value === "function" ? value(current) : value;
      writeStored(key, next);
      return next;
    });
  };

  return [open, setOpen];
}
