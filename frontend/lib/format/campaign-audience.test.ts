import { describe, expect, it } from "vitest";

import { sessionAudienceLabel } from "./campaign-audience";

describe("sessionAudienceLabel (#1029)", () => {
  it("counts students, not families, and says siblings share one email", () => {
    expect(sessionAudienceLabel(8, "Juniors")).toBe(
      "the families of 8 students on Juniors (one email per family)",
    );
    expect(sessionAudienceLabel(1, "Juniors")).toContain("1 student on");
    expect(sessionAudienceLabel(8, "Juniors")).not.toContain("8 families");
  });
});
