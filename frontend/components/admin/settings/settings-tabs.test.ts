import { describe, expect, it } from "vitest";

import { RETIRED_SETTINGS_PANELS, SETTINGS_TABS } from "./settings-tabs";

describe("Settings tabs (Settings overhaul Phase 3 PR 9)", () => {
  it("has no standalone Branding tab any more", () => {
    expect(SETTINGS_TABS.some((tab) => tab.key === "branding")).toBe(false);
  });

  it("labels the merged tab Academy profile, key still academy", () => {
    const academy = SETTINGS_TABS.find((tab) => tab.key === "academy");
    expect(academy).toEqual({ key: "academy", label: "Academy profile" });
  });

  it("maps the retired ?panel=branding to the Academy profile tab", () => {
    expect(RETIRED_SETTINGS_PANELS.branding).toBe("academy");
  });
});
