import { describe, expect, it } from "vitest";

import {
  classLevelNote,
  classTitleLevel,
  dateOfBirthError,
  localIsoDate,
  monthlyPriceLabel,
  reviewPriceLines,
  skillLevelLabel,
  SKILL_LEVEL_HINTS,
  waiverPerChildNote,
} from "@/lib/parent/onboarding-copy";

describe("sign-up wizard copy (S22)", () => {
  it("bounds the date of birth at today and explains a bad one", () => {
    const today = localIsoDate(new Date(2026, 10, 26));
    expect(today).toBe("2026-11-26");
    expect(dateOfBirthError("2018-04-12", today)).toBeNull();
    expect(dateOfBirthError("2026-11-26", today)).toBeNull();
    expect(dateOfBirthError("2026-11-27", today)).toBe("Date of birth can't be in the future.");
    expect(dateOfBirthError("2018-4", today)).toBe("Enter the date of birth as a full date.");
    expect(dateOfBirthError("", today)).toBeNull();
  });

  it("says per month on a class price, and never promises Free for a blank price", () => {
    expect(monthlyPriceLabel(8000)).toBe("$80.00 per month");
    expect(monthlyPriceLabel(0)).toBe("Free");
  });

  it("explains every skill level in one line", () => {
    for (const level of ["beginner", "intermediate", "advanced"] as const) {
      expect(SKILL_LEVEL_HINTS[level].length).toBeGreaterThan(0);
    }
  });

  it("notes, without blocking, a class listed for another level", () => {
    expect(classTitleLevel("Tuesday Intermediate")).toBe("intermediate");
    expect(classTitleLevel("Junior Beginners")).toBe("beginner");
    expect(classTitleLevel("Beginner to Advanced Mixed")).toBeNull();
    expect(classLevelNote("Tuesday Intermediate", "beginner")).toBe(
      "This class is listed as Intermediate; you chose Beginner. You can still pick it.",
    );
    expect(classLevelNote("Tuesday Intermediate", "intermediate")).toBeNull();
    expect(classLevelNote("Saturday Squad", "beginner")).toBeNull();
    expect(classLevelNote("Tuesday Intermediate", "")).toBeNull();
  });
});

describe("review step wording (S22 persona follow-up)", () => {
  it("gives a free class one plain line, not '0 of 4 classes' (S42)", () => {
    const zero = { amount_due_cents: 0, next_billing_amount_cents: 0, message: "0 of 4 classes" };
    expect(reviewPriceLines(zero)).toEqual(["Free class. Nothing to pay at checkout."]);
    const paid = { amount_due_cents: 6000, next_billing_amount_cents: 8000, message: "3 of 4 classes" };
    expect(reviewPriceLines(paid)).toEqual([
      "First month: $60.00 · 3 of 4 classes",
      "Starting next month: $80.00 per month",
    ]);
  });

  it("capitalises the level and names a missing one", () => {
    expect(skillLevelLabel("beginner")).toBe("Beginner");
    expect(skillLevelLabel("")).toBe("level not given");
  });
});

describe("waiverPerChildNote (Wave A follow-up)", () => {
  it("says the waiver is per child and names the child", () => {
    expect(waiverPerChildNote("Mateo")).toBe(
      "Each child needs their own signed waiver, so this one is for Mateo. Your name is already filled in.",
    );
    expect(waiverPerChildNote("  ")).toContain("for this child.");
  });
});
