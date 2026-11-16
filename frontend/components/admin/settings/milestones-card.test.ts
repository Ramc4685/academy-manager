import { describe, expect, it } from "vitest";

import { milestoneFormError } from "./milestones-card";

const form = (
  milestones: { kind: "skills_passed" | "levels_completed"; count: number }[],
) => ({
  milestones_enabled: true,
  milestones,
  share_name: "first_name" as const,
});

describe("milestoneFormError", () => {
  it("accepts an empty list and distinct thresholds", () => {
    expect(milestoneFormError(form([]))).toBeNull();
    expect(
      milestoneFormError(
        form([
          { kind: "skills_passed", count: 10 },
          { kind: "levels_completed", count: 10 },
        ]),
      ),
    ).toBeNull();
  });

  it("refuses duplicates and counts outside 1..1000", () => {
    expect(
      milestoneFormError(
        form([
          { kind: "skills_passed", count: 5 },
          { kind: "skills_passed", count: 5 },
        ]),
      ),
    ).toMatch(/once/);
    expect(
      milestoneFormError(form([{ kind: "skills_passed", count: 0 }])),
    ).toMatch(/1 to 1000/);
    expect(
      milestoneFormError(form([{ kind: "skills_passed", count: Number.NaN }])),
    ).toMatch(/1 to 1000/);
  });
});
