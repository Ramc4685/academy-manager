import { describe, expect, it } from "vitest";

import { offerExpiryLabel } from "./waitlist-offer";

describe("offerExpiryLabel", () => {
  it("names when the held seat moves on", () => {
    expect(offerExpiryLabel("2026-09-28T17:00:00Z", "America/Chicago")).toMatch(
      /^Held until .*12:00 PM CDT$/,
    );
  });

  it("returns null when there is no usable deadline", () => {
    expect(offerExpiryLabel(null)).toBeNull();
    expect(offerExpiryLabel(undefined)).toBeNull();
    expect(offerExpiryLabel("garbage")).toBeNull();
  });
});
