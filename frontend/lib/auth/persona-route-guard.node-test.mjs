import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PERSONA_PATH_MATCHER,
  decidePersonaRedirect,
  matchesPersonaPath,
  personaForPath,
  personaHintForRoles,
} from "./persona-route-guard.ts";

function decide(overrides = {}) {
  return decidePersonaRedirect({
    pathname: "/admin",
    search: "",
    personaHint: undefined,
    hasIdentity: false,
    bypassAuth: false,
    ...overrides,
  });
}

test("bounces a visitor with no session cookies to /login with the return path", () => {
  assert.equal(
    decide({ pathname: "/admin/students", search: "" }),
    "/login?returnTo=%2Fadmin%2Fstudents",
  );
});

test("keeps the query string in the return path", () => {
  assert.equal(
    decide({ pathname: "/parent/payments", search: "?invoice=inv_1" }),
    "/login?returnTo=%2Fparent%2Fpayments%3Finvoice%3Dinv_1",
  );
});

test("sends a wrong-persona visitor to their own home instead of /login", () => {
  assert.equal(
    decide({ pathname: "/admin", personaHint: "parent", hasIdentity: true }),
    "/parent/payments?access_denied=admin",
  );
});

test("lets the matching persona through", () => {
  assert.equal(
    decide({ pathname: "/admin/students", personaHint: "admin", hasIdentity: true }),
    null,
  );
});

test("lets an admin covering the coach surface through", () => {
  assert.equal(
    decide({ pathname: "/coach/today", personaHint: "admin,coach", hasIdentity: true }),
    null,
  );
});

test("fails open when the hint is missing or unrecognised", () => {
  assert.equal(decide({ pathname: "/admin", hasIdentity: true }), null);
  assert.equal(
    decide({ pathname: "/admin", personaHint: "gibberish", hasIdentity: true }),
    null,
  );
});

test("treats a persona hint alone as a signed-in signal", () => {
  // The identity cookie is SameSite=Strict and expires hourly; the Lax hint
  // is what survives an email link, so it must not bounce to /login.
  assert.equal(decide({ pathname: "/admin", personaHint: "admin" }), null);
});

test("passes everything through under the e2e auth bypass", () => {
  assert.equal(decide({ pathname: "/admin", bypassAuth: true }), null);
  assert.equal(
    decide({ pathname: "/admin", personaHint: "parent", hasIdentity: true, bypassAuth: true }),
    null,
  );
});

test("maps each guarded prefix to its own persona", () => {
  assert.equal(personaForPath("/admin"), "admin");
  assert.equal(personaForPath("/admin/students/abc"), "admin");
  assert.equal(personaForPath("/coach/today"), "coach");
  assert.equal(personaForPath("/parent/payments"), "parent");
  assert.equal(personaForPath("/platform/tenants"), "platform");
  assert.equal(personaForPath("/administrators"), null);
});

test("guards only the four persona shells", () => {
  assert.deepEqual([...PERSONA_PATH_MATCHER], [
    "/admin/:path*",
    "/coach/:path*",
    "/parent/:path*",
    "/platform/:path*",
  ]);
  for (const outside of ["/calendar", "/owner", "/student/dashboard", "/login", "/"]) {
    assert.equal(matchesPersonaPath(outside), false, outside);
    assert.equal(decide({ pathname: outside }), null, outside);
  }
});

test("each guarded persona redirects a mismatched hint to that hint's home", () => {
  assert.equal(
    decide({ pathname: "/coach/today", personaHint: "parent", hasIdentity: true }),
    "/parent/payments?access_denied=coach",
  );
  assert.equal(
    decide({ pathname: "/parent/payments", personaHint: "admin,coach", hasIdentity: true }),
    "/admin?access_denied=parent",
  );
  assert.equal(
    decide({ pathname: "/platform", personaHint: "coach", hasIdentity: true }),
    "/coach/today?access_denied=platform",
  );
});

test("derives the hint from the roles the backend reported", () => {
  assert.equal(personaHintForRoles(["parent"], false), "parent");
  // Admins and owners may cover the coach surface (#632), so the hint must
  // not lock them out of /coach.
  assert.equal(personaHintForRoles(["admin"], false), "admin,coach");
  assert.equal(personaHintForRoles(["owner"], false), "coach,owner");
  assert.equal(personaHintForRoles(["assistant_coach"], false), "coach");
  assert.equal(personaHintForRoles(["parent", "student"], false), "parent,student");
  assert.equal(personaHintForRoles(["admin"], true), "admin,coach,platform");
  assert.equal(personaHintForRoles([], false), "");
});

test("never routes an owner-only hint into a guarded shell it does not hold", () => {
  // owner is a scope, not a shell: /owner is outside the matcher and the
  // hint still names a home so the bounce is not a dead end.
  assert.equal(
    decide({ pathname: "/admin", personaHint: "coach,owner", hasIdentity: true }),
    "/coach/today?access_denied=admin",
  );
});
