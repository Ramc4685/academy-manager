import { describe, expect, it } from "vitest";

import {
  OWNER_ONLY_SETTINGS_PANELS,
  RETIRED_SETTINGS_EXTERNAL_REDIRECTS,
  RETIRED_SETTINGS_PANELS,
  SETTINGS_TABS,
} from "./settings-tabs";

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

describe("Session types moved to the Pricing page (Settings overhaul PR 11b)", () => {
  it("has no Session types tab any more", () => {
    expect(SETTINGS_TABS.some((tab) => (tab.key as string) === "session-types")).toBe(false);
  });

  it("redirects ?panel=session-types to /admin/pricing for everyone", () => {
    const redirect = RETIRED_SETTINGS_EXTERNAL_REDIRECTS["session-types"];
    expect(redirect(true)).toBe("/admin/pricing");
    // A plain admin lands on the page's owner-only panel, not a blank tab.
    expect(redirect(false)).toBe("/admin/pricing");
  });
});

describe("Settings tabs (Settings overhaul Phase 3 PR 11)", () => {
  it("renames Gateway to Integrations and Notify to Notifications", () => {
    const labels = Object.fromEntries(SETTINGS_TABS.map((tab) => [tab.key, tab.label]));
    expect(labels.integrations).toBe("Integrations");
    expect(labels.notifications).toBe("Notifications");
    expect(labels.gateway).toBeUndefined();
    expect(labels.notify).toBeUndefined();
  });

  it("orders the tabs as the plan does, Session types moved to Pricing", () => {
    expect(SETTINGS_TABS.map((tab) => tab.label)).toEqual([
      "Academy profile",
      "Billing rules",
      "Integrations",
      "Notifications",
      "Family policies",
      "Public page",
      "Curriculum",
    ]);
  });

  it("keeps Integrations owner-only, as Gateway was", () => {
    expect(OWNER_ONLY_SETTINGS_PANELS.has("integrations")).toBe(true);
    expect(OWNER_ONLY_SETTINGS_PANELS.has("notifications")).toBe(false);
    expect(OWNER_ONLY_SETTINGS_PANELS.has("curriculum")).toBe(false);
  });

  it("resolves every retired panel key to a real tab or an external page", () => {
    const live = new Set(SETTINGS_TABS.map((tab) => tab.key as string));
    const expected: Record<string, string> = {
      gateway: "integrations",
      notify: "notifications",
      branding: "academy",
      "self-service": "family-policies",
      fees: "billing-rules",
    };
    for (const [retired, target] of Object.entries(expected)) {
      expect(RETIRED_SETTINGS_PANELS[retired], retired).toBe(target);
      expect(live.has(target), target).toBe(true);
    }
    // No retired key may map to another retired key or a dead tab.
    for (const target of Object.values(RETIRED_SETTINGS_PANELS)) {
      expect(live.has(target)).toBe(true);
    }
    // data and roles leave Settings for other pages.
    expect(Object.keys(RETIRED_SETTINGS_EXTERNAL_REDIRECTS).sort()).toEqual(["data", "roles", "session-types"]);
    expect(RETIRED_SETTINGS_EXTERNAL_REDIRECTS.roles(true)).toBe("/admin/users");
    expect(RETIRED_SETTINGS_EXTERNAL_REDIRECTS.data(true)).toBe("/admin/reports");
  });

  it("maps Stripe's ?panel=gateway&stripe=... return link to Integrations", () => {
    // The settings page rewrites only `panel` and keeps the other params, so
    // `stripe=connected|error|refresh` survives the mapping.
    const params = new URLSearchParams("panel=gateway&stripe=connected");
    const active = RETIRED_SETTINGS_PANELS[params.get("panel") ?? ""];
    expect(active).toBe("integrations");
    params.set("panel", active);
    expect(params.get("stripe")).toBe("connected");
    expect(params.toString()).toBe("panel=integrations&stripe=connected");
  });
});
