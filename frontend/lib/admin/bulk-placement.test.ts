import { describe, expect, it } from "vitest";

import { summarizePlacement } from "./bulk-placement";

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
