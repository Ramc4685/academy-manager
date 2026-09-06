import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COACH_SURFACE_ROLES,
  availablePersonaViews,
  canSuperviseCoaching,
  isAssistantCoach,
  isOwner,
} from "./coach-supervisor.ts";

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

test("isOwner is true only when the owner scope is held", () => {
  assert.equal(isOwner(["owner"]), true);
  assert.equal(isOwner(["admin", "owner"]), true);
  assert.equal(isOwner(["admin"]), false);
  assert.equal(isOwner(["coach", "parent"]), false);
  assert.equal(isOwner([]), false);
});

test("assistant coaches never supervise coaching", () => {
  assert.equal(canSuperviseCoaching(["assistant_coach"]), false);
  assert.equal(canSuperviseCoaching(["assistant_coach", "parent"]), false);
});

test("isAssistantCoach is true only for an assistant without a lead role", () => {
  assert.equal(isAssistantCoach(["assistant_coach"]), true);
  assert.equal(isAssistantCoach(["assistant_coach", "parent"]), true);
  assert.equal(isAssistantCoach(["assistant_coach", "coach"]), false);
  assert.equal(isAssistantCoach(["assistant_coach", "admin"]), false);
  assert.equal(isAssistantCoach(["assistant_coach", "owner"]), false);
  assert.equal(isAssistantCoach(["coach"]), false);
  assert.equal(isAssistantCoach([]), false);
});

test("an assistant-only user gets the Coach view (assistant is not a view of its own)", () => {
  assert.deepEqual(availablePersonaViews(["assistant_coach"]), ["coach"]);
  assert.deepEqual(availablePersonaViews(["assistant_coach", "parent"]), ["coach", "parent"]);
  assert.deepEqual(availablePersonaViews(["assistant_coach", "coach"]), ["coach"]);
});

test("the coach surface admits coaches, assistants and supervisors only", () => {
  assert.deepEqual([...COACH_SURFACE_ROLES].sort(), ["admin", "assistant_coach", "coach", "owner"]);
});
