import assert from "node:assert/strict";
import { test } from "node:test";

import { buildProxyHeaders } from "./proxy-headers.ts";

test("maps the BFF auth bridge header to backend auth carriers", () => {
  const headers = buildProxyHeaders(
    new Headers({
      host: "blno-academy.courtmastr.com",
      "x-courtmastr-identity": "firebase-id-token",
    }),
    "https:"
  );

  assert.equal(headers.get("authorization"), "Bearer firebase-id-token");
  assert.equal(headers.get("x-courtmastr-auth"), "Bearer firebase-id-token");
  assert.equal(headers.get("x-courtmastr-identity"), null);
  assert.equal(headers.get("x-forwarded-host"), "blno-academy.courtmastr.com");
  assert.equal(headers.get("x-forwarded-proto"), "https");
  assert.equal(headers.get("host"), null);
});

test("keeps an existing Authorization header ahead of the bridge header", () => {
  const headers = buildProxyHeaders(
    new Headers({
      authorization: "Bearer original-token",
      "x-courtmastr-identity": "bridge-token",
    }),
    "https:"
  );

  assert.equal(headers.get("authorization"), "Bearer original-token");
  assert.equal(headers.get("x-courtmastr-auth"), "Bearer bridge-token");
});

test("maps the BFF identity cookie and strips it from the backend request", () => {
  const headers = buildProxyHeaders(
    new Headers({
      cookie: "theme=dark; __cm_identity=firebase-cookie-token; other=1",
    }),
    "https:"
  );

  assert.equal(headers.get("authorization"), "Bearer firebase-cookie-token");
  assert.equal(headers.get("x-courtmastr-auth"), "Bearer firebase-cookie-token");
  assert.equal(headers.get("cookie"), "theme=dark; other=1");
});
