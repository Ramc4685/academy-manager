import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveAuthDomain } from "./auth-domain.ts";

const CONFIGURED = "academy-courtmastr.firebaseapp.com";

test("uses the configured authDomain when proxy mode is off", () => {
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: CONFIGURED,
      proxyEnabled: false,
      pageHost: "blno-academy.courtmastr.com",
    }),
    CONFIGURED
  );
});

test("uses the page host when proxy mode is on (first-party auth)", () => {
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: CONFIGURED,
      proxyEnabled: true,
      pageHost: "blno-academy.courtmastr.com",
    }),
    "blno-academy.courtmastr.com"
  );
});

test("falls back to the configured authDomain during SSR", () => {
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: CONFIGURED,
      proxyEnabled: true,
      pageHost: undefined,
    }),
    CONFIGURED
  );
});

test("never proxies on localhost, with or without a port", () => {
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: CONFIGURED,
      proxyEnabled: true,
      pageHost: "localhost:3001",
    }),
    CONFIGURED
  );
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: CONFIGURED,
      proxyEnabled: true,
      pageHost: "127.0.0.1:3001",
    }),
    CONFIGURED
  );
});

test("keeps undefined configured domain when proxy mode is off", () => {
  assert.equal(
    resolveAuthDomain({
      configuredAuthDomain: undefined,
      proxyEnabled: false,
      pageHost: "blno-academy.courtmastr.com",
    }),
    undefined
  );
});
