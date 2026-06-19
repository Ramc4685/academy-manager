import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveBffApiOrigin } from "./proxy-origin.ts";

test("defaults the BFF proxy to local backend outside production", () => {
  assert.equal(resolveBffApiOrigin({ NODE_ENV: "development" }), "http://127.0.0.1:8001");
  assert.equal(resolveBffApiOrigin({ NODE_ENV: "test" }), "http://127.0.0.1:8001");
});

test("defaults the BFF proxy to production in production builds", () => {
  assert.equal(
    resolveBffApiOrigin({ NODE_ENV: "production" }),
    "https://api.academy.courtmastr.com"
  );
});

test("honors explicit BFF_API_ORIGIN over environment defaults", () => {
  assert.equal(
    resolveBffApiOrigin({
      NODE_ENV: "development",
      BFF_API_ORIGIN: "http://backend.local:8001",
    }),
    "http://backend.local:8001"
  );
});
