import assert from "node:assert/strict";
import { test } from "node:test";

import { shouldUseRedirectForGoogleSignIn } from "./google-sign-in-mode.ts";

test("uses redirect for iPhone Safari instead of popup", () => {
  assert.equal(
    shouldUseRedirectForGoogleSignIn({
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
      maxTouchPoints: 5,
      platform: "iPhone",
    }),
    true
  );
});

test("uses redirect for iOS Chrome instead of popup", () => {
  assert.equal(
    shouldUseRedirectForGoogleSignIn({
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1",
      maxTouchPoints: 5,
      platform: "iPhone",
    }),
    true
  );
});

test("uses redirect for touch iPadOS even with desktop-style platform", () => {
  assert.equal(
    shouldUseRedirectForGoogleSignIn({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
      maxTouchPoints: 5,
      platform: "MacIntel",
    }),
    true
  );
});

test("keeps popup for desktop Chrome", () => {
  assert.equal(
    shouldUseRedirectForGoogleSignIn({
      userAgent:
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
      maxTouchPoints: 0,
      platform: "MacIntel",
    }),
    false
  );
});
