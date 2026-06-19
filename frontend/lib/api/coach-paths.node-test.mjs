import assert from "node:assert/strict";
import { test } from "node:test";

import {
  coachDayHubPath,
  coachSessionBulkSkillStatusPath,
  coachSessionSkillsPath,
  coachStudentPassportPath,
} from "./coach-paths.ts";

test("builds the coach passport route instead of an admin or legacy route", () => {
  assert.equal(
    coachStudentPassportPath("student 1", "program/a"),
    "/coach/students/student%201/passport?program_id=program%2Fa"
  );
});

test("builds date-aware day hub and session skills routes", () => {
  assert.equal(coachDayHubPath("2026-06-19"), "/coach/day-hub?date=2026-06-19");
  assert.equal(
    coachSessionSkillsPath("occurrence 1", {
      date: "2026-06-19",
      programId: "program/a",
    }),
    "/coach/sessions/occurrence%201/skills?date=2026-06-19&program_id=program%2Fa"
  );
});

test("builds the session bulk skill status route", () => {
  assert.equal(
    coachSessionBulkSkillStatusPath("occurrence 1"),
    "/coach/sessions/occurrence%201/skills/bulk-status"
  );
});
