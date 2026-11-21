import { describe, expect, it } from "vitest";

import type { CopySessionResponse } from "@/lib/api/admin";

import { copyClassNotes, copySchedulePatch, existingCopyId } from "./copy-class-dialog";

const result = (over: Partial<CopySessionResponse>): CopySessionResponse => ({
  session: {} as CopySessionResponse["session"],
  price_copied: true,
  roster: [],
  ...over,
});

describe("copyClassNotes (A0-8)", () => {
  it("is empty for a clean copy, so the page can go straight to the new class", () => {
    expect(copyClassNotes(result({}), true)).toEqual([]);
  });

  it("names each student the seat check refused", () => {
    const notes = copyClassNotes(
      result({
        roster: [
          { student_id: "s1", full_name: "Ana Fake", ok: true, error_code: null, message: null },
          { student_id: "s2", full_name: "Ben Fake", ok: false, error_code: "Enrollment.CapacityExceeded", message: "Class is full" },
        ],
      }),
      false,
    );
    expect(notes).toEqual(["Ben Fake was not added: Class is full"]);
  });

  it("says the fee is missing only when the source had one and it did not come along", () => {
    expect(copyClassNotes(result({ price_copied: false }), true)).toEqual([
      "The new class has no fee yet. Ask the owner to set it.",
    ]);
    expect(copyClassNotes(result({ price_copied: false }), false)).toEqual([]);
  });
});

describe("copySchedulePatch", () => {
  const multi = { days_of_week: ["Mon", "Wed"], start_time: "17:00", end_time: "18:00" };

  it("sends nothing when the schedule is unchanged, so a multi-day class keeps every day", () => {
    expect(copySchedulePatch(multi, { days: ["Wed", "Mon"], startTime: "17:00", endTime: "18:00" })).toEqual({});
  });

  it("sends only the fields the admin changed", () => {
    expect(copySchedulePatch(multi, { days: ["Mon", "Wed"], startTime: "16:00", endTime: "18:00" })).toEqual({
      start_time: "16:00",
    });
    expect(copySchedulePatch(multi, { days: ["Tue", "Thu"], startTime: "17:00", endTime: "18:00" })).toEqual({
      days_of_week: ["Tue", "Thu"],
    });
  });
});

describe("existingCopyId", () => {
  it("returns the class a duplicate-series retry points at", () => {
    const err = Object.assign(new Error("exists"), {
      code: "Enrollment.DuplicateSessionSeries",
      details: { session_id: "sess-copy" },
    });
    expect(existingCopyId(err)).toBe("sess-copy");
  });

  it("ignores other errors", () => {
    const refused = Object.assign(new Error("x"), { code: "Enrollment.CopyRosterRefused" });
    expect(existingCopyId(refused)).toBeNull();
    expect(existingCopyId(new Error("network"))).toBeNull();
  });
});

