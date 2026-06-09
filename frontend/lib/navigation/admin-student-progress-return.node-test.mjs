import assert from "node:assert/strict";
import { test } from "node:test";

import {
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
