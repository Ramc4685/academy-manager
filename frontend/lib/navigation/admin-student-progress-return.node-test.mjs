import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildSessionSkillBoardHref,
  buildStudentProgressHref,
  resolveStudentProgressReturn,
} from "./admin-student-progress-return.ts";

test("builds student progress href with encoded program and return context", () => {
  const href = buildStudentProgressHref({
    studentId: "stu 123",
    programId: "program/abc",
    returnTo: "/admin/sessions/session 42",
    returnLabel: "Back to session",
  });

  assert.equal(
    href,
    "/admin/students/stu%20123/progress?program_id=program%2Fabc&return_to=%2Fadmin%2Fsessions%2Fsession+42&return_label=Back+to+session",
  );
});

test("resolves safe internal return links", () => {
  const result = resolveStudentProgressReturn({
    returnTo: "/admin/sessions/session-42",
    returnLabel: "Back to session",
  });

  assert.deepEqual(result, {
    href: "/admin/sessions/session-42",
    label: "Back to session",
  });
});

test("falls back when return target is missing or unsafe", () => {
  assert.deepEqual(resolveStudentProgressReturn({}), {
    href: "/admin/students",
    label: "All students",
  });

  assert.deepEqual(
    resolveStudentProgressReturn({
      returnTo: "https://example.com/admin/sessions/session-42",
      returnLabel: "Back to session",
    }),
    {
      href: "/admin/students",
      label: "All students",
    },
  );
});

// Issue #169: leaving the skill board to place an unplaced student dropped the
// program, so the placement screen fell back to the default program and the
// return trip landed on a board where the student still looked unplaced.
test("pins the program on the skill board href", () => {
  assert.equal(
    buildSessionSkillBoardHref({ sessionId: "sess 1", programId: "program/abc" }),
    "/admin/sessions/sess%201/skill-board?program_id=program%2Fabc",
  );
});

test("omits the program when the board has none", () => {
  assert.equal(
    buildSessionSkillBoardHref({ sessionId: "sess-1", programId: "" }),
    "/admin/sessions/sess-1/skill-board",
  );
  assert.equal(
    buildSessionSkillBoardHref({ sessionId: "sess-1" }),
    "/admin/sessions/sess-1/skill-board",
  );
});

test("round-trips the program through the placement link and back", () => {
  const boardHref = buildSessionSkillBoardHref({
    sessionId: "sess-1",
    programId: "prog-9",
  });
  const href = buildStudentProgressHref({
    studentId: "stu-1",
    programId: "prog-9",
    returnTo: boardHref,
    returnLabel: "Back to skill board",
  });

  const url = new URL(href, "https://academy.local");
  assert.equal(url.searchParams.get("program_id"), "prog-9");
  assert.equal(url.searchParams.get("return_to"), boardHref);
  assert.deepEqual(
    resolveStudentProgressReturn({
      returnTo: url.searchParams.get("return_to"),
      returnLabel: url.searchParams.get("return_label"),
    }),
    { href: boardHref, label: "Back to skill board" },
  );
});
