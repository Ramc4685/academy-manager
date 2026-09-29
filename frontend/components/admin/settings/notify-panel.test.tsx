import { describe, expect, it } from "vitest";

import { normalize, toPayload } from "./notify-panel";

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
