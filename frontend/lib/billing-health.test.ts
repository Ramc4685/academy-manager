import { describe, expect, it } from "vitest";

import { healthPillTone, truncationLine } from "./billing-health";

describe("healthPillTone", () => {
  it("maps the three verdict states", () => {
    expect(healthPillTone("blocked").tone).toBe("red");
    expect(healthPillTone("attention").tone).toBe("amber");
    expect(healthPillTone("ok").tone).toBe("green");
  });

  it("never calls an unknown state healthy", () => {
    // The bug this page was rebuilt to remove was a green pill above a red
    // card; an unreadable state must not resurrect it.
    expect(healthPillTone("something-new").tone).toBe("amber");
    expect(healthPillTone(undefined).tone).toBe("amber");
    expect(healthPillTone(null).tone).toBe("amber");
    expect(healthPillTone("").tone).toBe("amber");
  });
});

describe("truncationLine", () => {
  it("says nothing when the list holds everything", () => {
    expect(truncationLine(3, 3)).toBeNull();
    expect(truncationLine(50, 0)).toBeNull();
  });

  it("names both numbers when the capped list hides some", () => {
    expect(truncationLine(50, 214)).toBe(
      "Showing the 50 most recent of 214 quarantined events.",
    );
  });
});
