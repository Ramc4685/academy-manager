"use client";

import { useEffect } from "react";

import { initSentry } from "@/lib/observability/sentry";

/**
 * Mounts once in the root layout and boots the browser error SDK. Renders
 * nothing; a no-op when `NEXT_PUBLIC_SENTRY_DSN` is unset (the SDK is not even
 * downloaded in that case).
 */
export function SentryInit() {
  useEffect(() => {
    void initSentry();
  }, []);
  return null;
}
