import { describe, expect, it } from "vitest";

import type { OnboardingApplication } from "@/lib/api/parent";
import {
  firstIncompleteStep,
  nextStep,
  onboardingOrder,
  onboardingSearch,
  resumeStep,
} from "@/lib/parent/onboarding-steps";

const parent = { first_name: "Rosa", last_name: "Alvarez", phone: "555-0142", heard_from: "", referral_code: "" };
const child = {
  first_name: "Lucia",
  last_name: "Alvarez",
  date_of_birth: "2018-04-12",
  skill_level: "beginner",
  emergency_contact_name: "Rosa Alvarez",
  emergency_contact_phone: "555-0142",
  medical_notes: "",
};
const blankChild = { ...child, first_name: "", last_name: "", date_of_birth: "", emergency_contact_name: "", emergency_contact_phone: "" };

function app(overrides: Partial<OnboardingApplication> = {}): OnboardingApplication {
  return {
    application_id: "app-1",
    status: "DRAFT",
    parent_profile: { ...parent, first_name: "", last_name: "", phone: "" },
    child_profile: blankChild,
    selected_session_id: null,
    waiver_accepted: false,
    expires_at: "2026-12-01T00:00:00Z",
    ...overrides,
  } as OnboardingApplication;
}

describe("onboarding resume step", () => {
  it("starts a brand-new family on the parent step", () => {
    expect(firstIncompleteStep(app())).toBe("parent");
  });

  it("starts a second child at Child: the parent step carried over", () => {
    expect(resumeStep(app({ parent_profile: parent }), null)).toBe("child");
  });

  it("stays on Waiver after a reload", () => {
    const onWaiver = app({ parent_profile: parent, child_profile: child });
    expect(resumeStep(onWaiver, "waiver")).toBe("waiver");
  });

  it("lets the parent revisit an earlier step but not skip ahead", () => {
    const onWaiver = app({ parent_profile: parent, child_profile: child });
    expect(resumeStep(onWaiver, "parent")).toBe("parent");
    expect(resumeStep(onWaiver, "review")).toBe("waiver");
    expect(resumeStep(onWaiver, "bogus")).toBe("waiver");
  });

  it("follows the class-first order", () => {
    const classFirst = app({ parent_profile: parent, child_profile: child, waiver_class_first: true });
    expect(firstIncompleteStep(classFirst)).toBe("session");
  });

  it("skips the waiver step when there is no waiver to sign (S47)", () => {
    const noWaiver = app({ parent_profile: parent, child_profile: child, waiver_to_sign: false });
    expect(onboardingOrder(noWaiver)).toEqual(["parent", "child", "session", "review"]);
    expect(firstIncompleteStep(noWaiver)).toBe("session");
    expect(resumeStep(noWaiver, "waiver")).toBe("session");
    expect(nextStep(noWaiver, "child")).toBe("session");
    // Class-first: the session's patch can drop the step while the parent is on it.
    const classFirst = { ...noWaiver, waiver_class_first: true };
    expect(nextStep(classFirst, "session")).toBe("review");
    expect(nextStep(classFirst, "waiver")).toBe("review");
    expect(nextStep(app({ waiver_to_sign: true }), "child")).toBe("waiver");
  });

  it("keeps other query params when writing the step", () => {
    expect(onboardingSearch("?child=stu_1", "app-1", "waiver")).toBe("?child=stu_1&application=app-1&step=waiver");
  });
});
