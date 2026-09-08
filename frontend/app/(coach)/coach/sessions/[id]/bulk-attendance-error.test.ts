import { describe, expect, it } from "vitest";

import { formatBulkAttendanceError } from "./bulk-attendance-error";

const roster = [
  { student_id: "st1", full_name: "Alice" },
  { student_id: "st2", full_name: "Bob" },
  { student_id: "st-makeup", full_name: "Charlie" },
];

function rejection(student_ids: unknown) {
  return {
    status: 422,
    code: "Coaching.BulkStudentNotEnrolled",
    message: "students not actively enrolled",
    details: { student_ids, occurrence_id: "occ-today-1" },
  };
}

describe("formatBulkAttendanceError", () => {
  it("names one ineligible student by roster name", () => {
    const out = formatBulkAttendanceError(rejection(["st2"]), roster);
    expect(out?.ineligibleIds).toEqual(["st2"]);
    expect(out?.message).toContain("Bob isn't eligible");
    expect(out?.message).toContain("Nothing was saved");
  });

  it("joins several names and falls back to the id when the roster lacks it", () => {
    const out = formatBulkAttendanceError(rejection(["st1", "st2", "ghost"]), roster);
    expect(out?.ineligibleIds).toEqual(["st1", "st2", "ghost"]);
    expect(out?.message).toContain("Alice, Bob and ghost aren't eligible");
  });

  it("returns null for other errors so the generic path handles them", () => {
    expect(formatBulkAttendanceError({ status: 409, code: "Coaching.ConflictAttendanceExists" }, roster)).toBeNull();
    expect(formatBulkAttendanceError(new Error("network"), roster)).toBeNull();
  });

  it("still explains the rejection when the server sends no ids", () => {
    const out = formatBulkAttendanceError(rejection(undefined), roster);
    expect(out?.ineligibleIds).toEqual([]);
    expect(out?.message).toContain("Refresh the roster");
  });
});
