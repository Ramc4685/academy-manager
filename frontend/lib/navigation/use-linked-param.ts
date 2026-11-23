"use client";

import { useEffect, useState } from "react";

/**
 * A query param a notification or email link landed with (`?message=`,
 * `?occurrence=`), read once after mount. Reading `window.location` instead of
 * `useSearchParams` keeps the page free of a Suspense boundary; push taps do a
 * full `location.assign`, so the param is always present on first mount.
 */
export function useLinkedParam(name: string): string | null {
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => {
    setValue(new URLSearchParams(window.location.search).get(name) || null);
  }, [name]);
  return value;
}
