import { describe, expect, it } from "vitest";

import { isBadmintonSport, titleCase } from "./page";

describe("isBadmintonSport (row 13)", () => {
  it("is true for badminton, case-insensitively", () => {
    expect(isBadmintonSport("badminton")).toBe(true);
    expect(isBadmintonSport("Badminton")).toBe(true);
    expect(isBadmintonSport("BADMINTON")).toBe(true);
  });

  it("defaults to badminton when the academy sport is unset", () => {
    // Mirrors the backend's read-time default: every academy that predates
    // the `sport` field, including BLNO, reads as badminton.
    expect(isBadmintonSport(undefined)).toBe(true);
  });

  it("is false for any other sport", () => {
    expect(isBadmintonSport("tennis")).toBe(false);
    expect(isBadmintonSport("")).toBe(false);
  });
});

describe("titleCase", () => {
  it("capitalises the first letter only", () => {
    expect(titleCase("badminton")).toBe("Badminton");
    expect(titleCase("tennis")).toBe("Tennis");
  });

  it("handles an empty string", () => {
    expect(titleCase("")).toBe("");
  });
});
