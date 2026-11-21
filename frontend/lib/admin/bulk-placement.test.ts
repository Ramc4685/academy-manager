import { describe, expect, it } from "vitest";

import { summarizePlacement, visibleSelection } from "./bulk-placement";

describe("summarizePlacement", () => {
  it("counts placements and explains refusals", () => {
    expect(summarizePlacement([{ student_id: "a", outcome: "placed" }])).toBe(
      "1 student placed.",
    );
    expect(
      summarizePlacement([
        { student_id: "a", outcome: "placed" },
        { student_id: "b", outcome: "refused", code: "StudentProgress.LevelUpInProgress" },
        { student_id: "c", outcome: "refused", code: "Other" },
      ]),
    ).toBe("1 student placed. 2 not moved: a level-up is being approved right now; it was refused.");
  });
});

describe("visibleSelection", () => {
  it("drops selected students a filter change hid, so bulk placement never sends them", () => {
    const pickedUnderAllActions = ["placed-kid", "new-kid"];
    const rowsAfterFilter = ["new-kid", "other-kid"];
    expect(visibleSelection(pickedUnderAllActions, rowsAfterFilter)).toEqual(["new-kid"]);
    expect(visibleSelection(pickedUnderAllActions, [])).toEqual([]);
  });
});
