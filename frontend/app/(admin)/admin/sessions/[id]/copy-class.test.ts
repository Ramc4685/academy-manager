import { describe, expect, it } from "vitest";

import type { CopySessionResponse } from "@/lib/api/admin";

import { copyClassNotes } from "./copy-class-dialog";

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
