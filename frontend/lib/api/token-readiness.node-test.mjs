import assert from "node:assert/strict";
import { test } from "node:test";

import { getReadyIdToken } from "../auth/token-readiness.ts";

test("waits for Firebase auth state before returning no token", async () => {
  const user = {
    getIdToken: async () => "ready-token",
  };
  const authState = { currentUser: null };

  const tokenPromise = getReadyIdToken(
    authState,
    (callback) => {
      const timer = setTimeout(() => callback(user), 5);
      return () => clearTimeout(timer);
    },
    { timeoutMs: 50 }
  );

  assert.equal(await tokenPromise, "ready-token");
});

test("returns null when Firebase auth state never produces a user", async () => {
  const authState = { currentUser: null };

  const token = await getReadyIdToken(
    authState,
    () => () => undefined,
    { timeoutMs: 1 }
  );

  assert.equal(token, null);
});
