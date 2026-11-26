import { describe, expect, it } from "vitest";

import { milestoneCopy } from "./parent-home";

const now = new Date("2026-11-26T12:00:00Z");

describe("milestoneCopy (S18)", () => {
  it("calls only a passed skill a milestone", () => {
    expect(
      milestoneCopy({ kind: "skill", label: "Split step", at: "2026-11-25T20:00:00Z" }, "America/Chicago", now),
    ).toBe("Split step · Yesterday");
  });

  it("labels an in-progress skill as Working on", () => {
    expect(
      milestoneCopy({ kind: "working_on", label: "Split step", at: "2026-11-25T20:00:00Z" }, "America/Chicago", now),
    ).toBe("Working on: Split step · Yesterday");
  });

  it("labels a shared note as a coach note", () => {
    expect(milestoneCopy({ kind: "note", label: "Nice footwork", at: "2026-11-25T20:00:00Z" }, "America/Chicago", now)).toMatch(
      /^Coach note: Nice footwork/,
    );
  });
});
