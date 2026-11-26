import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import type { AdminStudentAttendanceView } from "@/lib/api/admin";

import { occurrenceAttendanceRows } from "./occurrence-attendance-rows";

function mark(studentId: string, extra: Partial<AdminStudentAttendanceView> = {}): AdminStudentAttendanceView {
  return {
    attendance_id: `att-${studentId}`,
    occurrence_id: "occ-1",
    session_id: "s-1",
    student_id: studentId,
    status: "absent",
    previous_status: null,
    corrected_by: null,
    corrected_at: null,
    correction_reason: null,
    marked_by: "coach-1",
    marked_at: "2026-11-21T15:00:00Z",
    ...extra,
  };
}

describe("occurrenceAttendanceRows (S25)", () => {
  it("names a transferred child from the server and never shows a raw id", () => {
    const rows = occurrenceAttendanceRows(
      [mark("stu-dev", { student_name: "Dev Patel" }), mark("stu-gone", { student_name: null })],
      new Map([["stu-sam", "Sam Demo"]]),
      new Map([["stu-sam", "Sam Demo"]]),
    );
    expect(rows.map((row) => row.name)).toEqual(["Dev Patel", "Former student", "Sam Demo"]);
    expect(rows.some((row) => row.name.startsWith("stu-"))).toBe(false);
  });

  it("lists roster children without a mark so an admin can give one", () => {
    const rows = occurrenceAttendanceRows(
      [mark("stu-sam", { student_name: "Sam Demo" })],
      new Map([
        ["stu-sam", "Sam Demo"],
        ["stu-alex", "Alex Demo"],
      ]),
      new Map([
        ["stu-sam", "Sam Demo"],
        ["stu-alex", "Alex Demo"],
      ]),
    );
    expect(rows.map((row) => [row.studentId, row.mark === null])).toEqual([
      ["stu-sam", false],
      ["stu-alex", true],
    ]);
  });

  it("does not offer a mark to a past enrollment with no mark", () => {
    const rows = occurrenceAttendanceRows(
      [mark("stu-left", { student_name: null })],
      new Map([
        ["stu-sam", "Sam Demo"],
        ["stu-left", "Lee Left"],
        ["stu-gone", "Gus Gone"],
      ]),
      new Map([["stu-sam", "Sam Demo"]]),
    );
    expect(rows.map((row) => [row.name, row.mark === null])).toEqual([
      ["Lee Left", false],
      ["Sam Demo", true],
    ]);
  });
});

describe("the class-date attendance dialog (S25)", () => {
  const src = readFileSync(path.join(__dirname, "SessionEditing.tsx"), "utf8");

  it("corrects through the admin PATCH with a required reason", () => {
    expect(src).toContain("correctStudentAttendance(occurrenceId, correctTarget.studentId");
    expect(src).toContain(
      "disabled={correctMutation.isPending || !correctStatus || reason.trim().length === 0}",
    );
  });

  it("keeps the scheduled coach out of the replacement list", () => {
    expect(src).toContain(".filter((coach) => coach.user_id !== scheduled)");
    // A one-coach academy gets a plain message, never a raw coach-id box.
    expect(src).toContain("No other coach to choose.");
    expect(src).not.toContain('"Coach reference"');
  });

  it("shows a cancelled date's reason on the row", () => {
    expect(src).toContain("occurrence-cancel-reason-${occurrence.occurrence_id}");
  });
});
