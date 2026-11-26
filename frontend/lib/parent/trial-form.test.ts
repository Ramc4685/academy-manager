import { describe, expect, it } from "vitest";

import { TRIAL_SUCCESS, trialMissingField, type TrialFormState } from "./trial-form";

const full: TrialFormState = {
  studentRef: "existing_student",
  studentId: "stu-1",
  prospectiveName: "",
  sessionId: "sess-1",
  preferredStart: "2026-12-01",
  preferredEnd: "2026-12-15",
};

describe("trialMissingField", () => {
  it("is null when the form is complete", () => {
    expect(trialMissingField(full)).toBeNull();
  });

  it("names the missing date instead of disabling silently", () => {
    expect(trialMissingField({ ...full, preferredEnd: "" })).toBe("Pick the last day that suits you.");
    expect(trialMissingField({ ...full, preferredStart: "" })).toBe(
      "Pick the first day that suits you.",
    );
  });

  it("asks for the new child's name, then the class, in form order", () => {
    expect(
      trialMissingField({ ...full, studentRef: "prospective", prospectiveName: " ", sessionId: "" }),
    ).toBe("Add the child's name.");
    expect(trialMissingField({ ...full, sessionId: "" })).toBe("Choose a class.");
  });

  it("refuses an end before the start", () => {
    expect(trialMissingField({ ...full, preferredEnd: "2026-11-30" })).toMatch(/on or after/);
  });

  it("confirms the request with a success toast", () => {
    expect(TRIAL_SUCCESS.title).toBe("Trial requested");
  });
});
