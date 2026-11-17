import { describe, expect, it } from "vitest";

import { aiLimitsForm, aiLimitsPayload, normalize, toPayload } from "./notify-panel";

describe("notify panel win-back switch (hardcoded-values row 10)", () => {
  it("reads a missing setting as on, matching the backend default", () => {
    expect(normalize({ daily_digest_to_admin: false }).win_back_enabled).toBe(true);
    expect(normalize(null).win_back_enabled).toBe(true);
    expect(normalize({ win_back_enabled: false }).win_back_enabled).toBe(false);
  });

  it("sends only the switch when only the switch changed", () => {
    const original = normalize({ daily_digest_to_admin: true });
    expect(toPayload(original, { ...original, win_back_enabled: false })).toEqual({
      win_back_enabled: false,
    });
    expect(toPayload(original, original)).toEqual({});
  });
});

describe("notify panel trial nudges switch", () => {
  it("reads a missing setting as on and sends only the switch", () => {
    expect(normalize(null).trial_nudges_enabled).toBe(true);
    expect(normalize({ trial_nudges_enabled: false }).trial_nudges_enabled).toBe(false);
    const original = normalize({ daily_digest_to_admin: true });
    expect(toPayload(original, { ...original, trial_nudges_enabled: false })).toEqual({
      trial_nudges_enabled: false,
    });
  });
});

describe("AI limits form (L13)", () => {
  const view = {
    monthly_call_cap: 200,
    daily_call_caps: { technique_observation: 30 },
    coach_review_narratives: true,
    features: ["technique_observation", "skill_ladder"],
  };

  it("shows a feature with no daily limit as a blank box and round-trips", () => {
    const form = aiLimitsForm(view);
    expect(form.daily).toEqual({ technique_observation: "30", skill_ladder: "" });
    expect(aiLimitsPayload(form)).toEqual({
      monthly_call_cap: 200,
      daily_call_caps: { technique_observation: 30 },
      coach_review_narratives: true,
    });
  });

  it("refuses a value out of range or not a whole number", () => {
    const form = aiLimitsForm(view);
    expect(aiLimitsPayload({ ...form, monthly: "5001" })).toHaveProperty("error");
    expect(aiLimitsPayload({ ...form, monthly: "1.5" })).toHaveProperty("error");
    expect(
      aiLimitsPayload({ ...form, daily: { ...form.daily, skill_ladder: "-2" } })
    ).toHaveProperty("error");
  });
});
