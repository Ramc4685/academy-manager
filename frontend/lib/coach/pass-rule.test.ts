import { describe, expect, it } from "vitest";

import { needsLead, passRuleChip, passRuleLine } from "./pass-rule";

describe("pass rule copy", () => {
  it("reads the rule and the tries so far", () => {
    expect(passRuleChip({}, undefined)).toBe("Tap");
    expect(passRuleChip({ pass_rule: "N_TRIES", pass_tries: 3 }, { tries: 1 })).toBe("1 of 3");
    expect(passRuleChip({ pass_rule: "N_TRIES", pass_tries: null }, undefined)).toBe("0 of 3");
    expect(passRuleChip({ pass_rule: "LEAD_COACH" }, undefined)).toBe("Lead coach");
    expect(passRuleLine({ pass_rule: "N_TRIES", pass_tries: 4 })).toContain("4 taps");
    expect(passRuleLine({})).toBe("One tap passes it.");
  });

  it("holds back lead-only taps from assistants only", () => {
    expect(needsLead({ pass_rule: "LEAD_COACH" }, true)).toBe(true);
    expect(needsLead({ pass_rule: "LEAD_COACH" }, false)).toBe(false);
    expect(needsLead({ pass_rule: "ONE_TAP" }, true)).toBe(false);
  });
});
