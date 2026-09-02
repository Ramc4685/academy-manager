import assert from "node:assert/strict";
import { test } from "node:test";

import { availablePersonaViews, canSuperviseCoaching } from "./coach-supervisor.ts";

test("admins and owners can supervise coaching; others cannot", () => {
  assert.equal(canSuperviseCoaching(["admin"]), true);
  assert.equal(canSuperviseCoaching(["owner"]), true);
  assert.equal(canSuperviseCoaching(["admin", "coach"]), true);
  assert.equal(canSuperviseCoaching(["coach"]), false);
  assert.equal(canSuperviseCoaching(["parent", "student"]), false);
  assert.equal(canSuperviseCoaching([]), false);
});

test("an admin-only user gets a Coach view without holding the coach role", () => {
  assert.deepEqual(availablePersonaViews(["admin"]), ["admin", "coach"]);
});

test("an owner-only user gets only the Coach view (owner is a scope, not a view)", () => {
  assert.deepEqual(availablePersonaViews(["owner"]), ["coach"]);
});

test("views keep switcher order and never duplicate coach", () => {
  assert.deepEqual(availablePersonaViews(["parent", "coach", "admin"]), [
    "admin",
    "coach",
    "parent",
  ]);
  assert.deepEqual(availablePersonaViews(["coach"]), ["coach"]);
  assert.deepEqual(availablePersonaViews(["student", "parent"]), ["parent", "student"]);
});
