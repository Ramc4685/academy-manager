import { describe, expect, it } from "vitest";

import { fixItemsFor } from "./FixSomethingPanel";

describe("fixItemsFor (#928 card charges are owner-only)", () => {
  it("hides every money-moving fix, card charge included, from a non-owner", () => {
    const kinds = fixItemsFor(false).map((it) => it.kind);
    expect(kinds).not.toContain("charge_card");
    expect(kinds).not.toContain("void");
    expect(kinds).not.toContain("refund");
    expect(kinds).not.toContain("discount_once");
  });

  it("offers the owner the card charge alongside void, refund and discount", () => {
    expect(fixItemsFor(true).map((it) => it.kind)).toEqual([
      "void",
      "refund",
      "discount_once",
      "charge_card",
    ]);
  });
});
