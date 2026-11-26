import { describe, expect, it } from "vitest";

import type { ParentSelfProfile } from "@/lib/api/parent";
import { gapBadgeText, parentGapLabels, profileGapSummary } from "@/lib/parent/profile-gaps";

function profile(parent: string[], children: Record<string, string[]> = {}): ParentSelfProfile {
  return {
    user_id: "u1",
    display_name: "Rosa Alvarez",
    email: "rosa.alvarez@example.com",
    email_confirmed: true,
    phone: null,
    children: [{ student_id: "stu_1", full_name: "Lucia Alvarez" }],
    gaps: { parent, children, is_complete: false },
  } as unknown as ParentSelfProfile;
}

describe("profile gaps (S23)", () => {
  it("names the missing field instead of '1 missing'", () => {
    expect(gapBadgeText(parentGapLabels(["phone"]))).toBe("Missing: your phone number");
    expect(profileGapSummary(profile(["phone"]))).toBe("Still needed: your phone number.");
  });

  it("names a child's gaps with the child's first name", () => {
    expect(profileGapSummary(profile(["phone"], { stu_1: ["date_of_birth"] }))).toBe(
      "Still needed: your phone number and Lucia's date of birth.",
    );
  });

  it("clears once the saved profile has no gaps", () => {
    // After save the response replaces the cached profile; nothing is left to name.
    expect(gapBadgeText(parentGapLabels([]))).toBeNull();
    expect(profileGapSummary(profile([], { stu_1: [] }))).toBeNull();
  });
});
