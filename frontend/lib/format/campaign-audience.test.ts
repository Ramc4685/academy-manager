import { describe, expect, it } from "vitest";

import { campaignAudienceLabel } from "./campaign-audience";

describe("campaignAudienceLabel (#1029)", () => {
  it("reports the resolved addresses and families, not students", () => {
    const label = campaignAudienceLabel(
      { status: "ready", counts: { recipient_count: 7, family_count: 7, contact_count: 0 } },
      "on Juniors",
    );
    expect(label).toBe("7 email recipients on Juniors (7 families)");
    expect(label).not.toContain("8");
  });

  it("separates opted-in family contacts from families", () => {
    expect(
      campaignAudienceLabel(
        { status: "ready", counts: { recipient_count: 8, family_count: 7, contact_count: 1 } },
        "on Juniors",
      ),
    ).toBe("8 email recipients on Juniors (7 families + 1 family contact)");
  });

  it("never states a number while loading or after an error", () => {
    expect(campaignAudienceLabel({ status: "loading" }, "on Juniors")).toBe(
      "on Juniors (counting recipients…)",
    );
    expect(campaignAudienceLabel({ status: "error" }, "on Juniors")).toMatch(/unavailable/);
    expect(campaignAudienceLabel({ status: "error" }, "on Juniors")).not.toMatch(/\d/);
  });

  it("uses singular nouns for one", () => {
    expect(
      campaignAudienceLabel(
        { status: "ready", counts: { recipient_count: 1, family_count: 1, contact_count: 0 } },
        "in the academy",
      ),
    ).toBe("1 email recipient in the academy (1 family)");
  });
});
