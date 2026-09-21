"use client";

import { useEffect, useState } from "react";

import { listNeedsReview } from "./queue";

/**
 * How many marks are waiting in the coach's Needs-review tray (issue #841).
 *
 * The tray was previously reachable only from a link inside a session that had
 * already failed, so a coach who navigated away never learned that a mark had
 * not saved. The shell shows a badge when this is non-zero.
 *
 * Polls rather than subscribes: the queue is IndexedDB with no change
 * notification, and the sync loop writes to it from outside React. 10s is far
 * below the time it takes a coach to act on a stale count, and the read is a
 * handful of rows.
 */
export function useNeedsReviewCount(enabled = true): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setCount(0);
      return;
    }
    let cancelled = false;
    async function read() {
      try {
        const items = await listNeedsReview();
        if (!cancelled) setCount(items.length);
      } catch {
        // No IndexedDB (private mode, SSR hydration race): no badge, no crash.
      }
    }
    void read();
    const timer = setInterval(() => void read(), 10_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return count;
}
