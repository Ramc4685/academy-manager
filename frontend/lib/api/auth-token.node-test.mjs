import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveApiAuthToken } from "./auth-token.ts";

test("uses an explicit auth token instead of reading ambient Firebase state", async () => {
  let ambientTokenLookups = 0;

  const token = await resolveApiAuthToken("signed-in-user-token", async () => {
    ambientTokenLookups += 1;
    return "ambient-token";
  });

  assert.equal(token, "signed-in-user-token");
  assert.equal(ambientTokenLookups, 0);
});
