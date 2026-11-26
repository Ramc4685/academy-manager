import { describe, expect, it } from "vitest";

import { isInstallDismissed, showInstallCardOn } from "./install-prompt";

const store = (value: string | null) => ({ getItem: () => value });

describe("isInstallDismissed (S19)", () => {
  it("is dismissed while the 30-day window is open", () => {
    expect(isInstallDismissed(store(String(2_000)), 1_000)).toBe(true);
  });
  it("shows again once the window has passed or was never set", () => {
    expect(isInstallDismissed(store(String(500)), 1_000)).toBe(false);
    expect(isInstallDismissed(store(null), 1_000)).toBe(false);
  });
  it("treats blocked storage as not dismissed", () => {
    const blocked = {
      getItem: () => {
        throw new Error("SecurityError");
      },
    };
    expect(isInstallDismissed(blocked, 1_000)).toBe(false);
    expect(isInstallDismissed(null, 1_000)).toBe(false);
  });
});

describe("showInstallCardOn (S19)", () => {
  it("shows only on Today", () => {
    expect(showInstallCardOn("/coach/today")).toBe(true);
    expect(showInstallCardOn("/coach/sessions")).toBe(false);
    expect(showInstallCardOn("/coach/profile")).toBe(false);
    expect(showInstallCardOn("/coach/today/plan")).toBe(false);
    expect(showInstallCardOn(null)).toBe(false);
  });
});
