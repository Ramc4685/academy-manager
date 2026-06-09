import assert from "node:assert/strict";
import { test } from "node:test";

import { canonicalizeRequestUrl } from "./canonical-host.ts";

test("redirects acamedy typo host to academy host and preserves path", () => {
  const redirected = canonicalizeRequestUrl(
    new URL("https://acamedy.courtmastr.com/login?next=%2Fadmin")
  );

  assert.equal(
    redirected?.toString(),
    "https://academy.courtmastr.com/login?next=%2Fadmin"
  );
});

test("leaves canonical academy host unchanged", () => {
  const redirected = canonicalizeRequestUrl(
    new URL("https://academy.courtmastr.com/login")
  );

  assert.equal(redirected, null);
});
