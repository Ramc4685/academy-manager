import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clearBffIdentityCookie,
  setBffIdentityCookie,
} from "./auth-bridge-cookie.ts";

function withBrowserCookieTarget(protocol, fn) {
  const originalDocument = globalThis.document;
  const originalWindow = globalThis.window;
  const writes = [];

  globalThis.document = {
    set cookie(value) {
      writes.push(value);
    },
  };
  globalThis.window = {
    location: { protocol },
  };

  try {
    fn(writes);
  } finally {
    if (originalDocument === undefined) {
      delete globalThis.document;
    } else {
      globalThis.document = originalDocument;
    }
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

test("sets the BFF identity bridge cookie for same-origin API requests", () => {
  withBrowserCookieTarget("http:", (writes) => {
    setBffIdentityCookie("token with spaces");

    assert.equal(writes.length, 1);
    assert.match(writes[0], /^__cm_identity=token%20with%20spaces;/);
    assert.match(writes[0], /Path=\//);
    assert.match(writes[0], /SameSite=Strict/);
    assert.match(writes[0], /Max-Age=3600/);
    assert.doesNotMatch(writes[0], /Secure/);
  });
});

test("clears stale BFF identity bridge cookies before login retries", () => {
  withBrowserCookieTarget("https:", (writes) => {
    clearBffIdentityCookie();

    assert.equal(writes.length, 1);
    assert.match(writes[0], /^__cm_identity=;/);
    assert.match(writes[0], /Path=\//);
    assert.match(writes[0], /SameSite=Strict/);
    assert.match(writes[0], /Max-Age=0/);
    assert.match(writes[0], /Secure/);
  });
});
