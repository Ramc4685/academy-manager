import assert from "node:assert/strict";
import { test } from "node:test";

import { buildProxyHeaders, buildProxyResponseHeaders } from "./proxy-headers.ts";

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

test("mints an X-Request-ID when the browser sent none", () => {
  const headers = buildProxyHeaders(new Headers({ host: "a.courtmastr.com" }), "https:");

  const requestId = headers.get("x-request-id");
  assert.ok(requestId, "request id should be minted");
  assert.match(requestId, /^[A-Za-z0-9._-]{1,128}$/);
});

test("keeps a valid inbound X-Request-ID untouched", () => {
  const headers = buildProxyHeaders(
    new Headers({ "x-request-id": "retry-01.abc_DEF" }),
    "https:"
  );

  assert.equal(headers.get("x-request-id"), "retry-01.abc_DEF");
});

test("replaces an X-Request-ID the backend validator would reject", () => {
  for (const forged of ["has space", "x".repeat(129), "semi;colon", ""]) {
    const headers = buildProxyHeaders(new Headers({ "x-request-id": forged }), "https:");
    const requestId = headers.get("x-request-id");
    assert.notEqual(requestId, forged);
    assert.match(requestId, /^[A-Za-z0-9._-]{1,128}$/);
  }
});

test("passes the backend's echoed X-Request-ID back to the browser", () => {
  const headers = buildProxyResponseHeaders(
    new Headers({ "x-request-id": "echoed-id", connection: "keep-alive" }),
    "minted-id"
  );

  assert.equal(headers.get("x-request-id"), "echoed-id");
  assert.equal(headers.get("connection"), null);
});

test("falls back to the minted X-Request-ID when upstream did not echo one", () => {
  const headers = buildProxyResponseHeaders(new Headers({ "content-type": "text/html" }), "minted-id");

  assert.equal(headers.get("x-request-id"), "minted-id");
});
