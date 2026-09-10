import { describe, expect, it } from "vitest";

import { defaultOutcomeFor, isMoneyOutcomeAllowed } from "./stop-all-classes-outcome";

describe("defaultOutcomeFor", () => {
  it("pre-selects credit when the academy's policy default is credit_mid_month", () => {
    expect(defaultOutcomeFor("credit_mid_month")).toBe("credit");
  });

  it("pre-selects the no-credit outcome for both no-credit policy defaults", () => {
    expect(defaultOutcomeFor("no_credit_mid_month")).toBe("adjustment");
    expect(defaultOutcomeFor("no_credit_end_of_period")).toBe("adjustment");
  });

  it("falls back to the no-credit outcome when the policy default is missing", () => {
    expect(defaultOutcomeFor(undefined)).toBe("adjustment");
  });
});

describe("isMoneyOutcomeAllowed", () => {
  it("lets anyone pick the no-credit outcome", () => {
    expect(isMoneyOutcomeAllowed("adjustment", true)).toBe(true);
    expect(isMoneyOutcomeAllowed("adjustment", false)).toBe(true);
  });

  it("gates credit behind the owner role", () => {
    expect(isMoneyOutcomeAllowed("credit", true)).toBe(true);
    expect(isMoneyOutcomeAllowed("credit", false)).toBe(false);
  });

  it("gates refund behind the owner role", () => {
    expect(isMoneyOutcomeAllowed("refund", true)).toBe(true);
    expect(isMoneyOutcomeAllowed("refund", false)).toBe(false);
  });
});
