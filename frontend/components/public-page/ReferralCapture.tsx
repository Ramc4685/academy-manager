"use client";

import { useEffect } from "react";

import { captureReferralCode } from "@/lib/referral-capture";

/**
 * Remembers `?ref=` from the academy page's URL (L9 C2). Mounted by the page
 * itself, whatever the trial state, so a family referred while trials are
 * paused (no trial form) keeps its code for registration.
 */
export function ReferralCapture() {
  useEffect(() => {
    captureReferralCode(window.location.search);
  }, []);
  return null;
}
