import { describe, expect, it } from "vitest";

import { defaultExternalSourceForSport, sourceTitlePlaceholder } from "./page";

describe("defaultExternalSourceForSport (row 13)", () => {
  it("defaults badminton programs to the BWF Shuttle Time citation", () => {
    expect(defaultExternalSourceForSport(true)).toBe("BWF_SHUTTLE_TIME");
  });

  it("defaults non-badminton programs to an academy-authored source", () => {
    expect(defaultExternalSourceForSport(false)).toBe("ACADEMY_CUSTOM");
  });
});

describe("sourceTitlePlaceholder (row 13)", () => {
  it("shows the Shuttle Time example only for badminton", () => {
    expect(sourceTitlePlaceholder(true)).toContain("Shuttle Time");
    expect(sourceTitlePlaceholder(false)).not.toContain("Shuttle Time");
  });
});
