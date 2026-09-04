import { describe, expect, it } from "vitest";

import { shouldAnchorLeft } from "./menu-anchor";

describe("shouldAnchorLeft", () => {
  it("flips a menu whose left edge is off screen", () => {
    expect(shouldAnchorLeft({ left: -120 })).toBe(true);
  });

  it("flips a menu whose left edge is inside the margin", () => {
    expect(shouldAnchorLeft({ left: 4 })).toBe(true);
  });

  it("leaves a menu that is fully on screen alone", () => {
    expect(shouldAnchorLeft({ left: 40 })).toBe(false);
  });

  it("honours a custom margin", () => {
    expect(shouldAnchorLeft({ left: 12 }, 16)).toBe(true);
    expect(shouldAnchorLeft({ left: 12 }, 8)).toBe(false);
  });
});
