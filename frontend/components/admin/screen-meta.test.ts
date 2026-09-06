import { describe, expect, it } from "vitest";

import {
  ADMIN_NAV,
  isOwnerOnlyRoute,
  metaForPath,
  navForRoles,
  type AdminNavGroup,
} from "./screen-meta";

const hrefs = (nav: ReadonlyArray<AdminNavGroup>) =>
  nav.flatMap((group) => group.items.map((item) => item.href));

describe("navForRoles", () => {
  it("returns the full nav, untouched, for owners", () => {
    expect(navForRoles(ADMIN_NAV, true)).toBe(ADMIN_NAV);
  });

  it("drops owner-only items for admins without the owner scope", () => {
    const visible = hrefs(navForRoles(ADMIN_NAV, false));
    expect(visible).not.toContain("/admin/payouts");
    expect(visible).not.toContain("/admin/reports");
    expect(visible).not.toContain("/admin/audit-logs");
    // Operations items survive.
    expect(visible).toContain("/admin/payments");
    expect(visible).toContain("/admin/expenses");
    expect(visible).toContain("/admin/settings");
    expect(visible).toContain("/admin/users");
    expect(visible).toContain("/admin/families");
    // Billing Setup was folded into Families (spec 2026-09-05-family-billing §6).
    expect(visible).not.toContain("/admin/billing-setup");
  });

  it("removes a group whose every item was owner-only", () => {
    const nav: AdminNavGroup[] = [
      {
        group: "MONEY",
        items: [
          { href: "/admin/reports", label: "Reports", icon: "chart", match: () => false, ownerOnly: true },
        ],
      },
      {
        group: "WORK",
        items: [{ href: "/admin", label: "Dashboard", icon: "home", match: () => false }],
      },
    ];
    expect(navForRoles(nav, false).map((group) => group.group)).toEqual(["WORK"]);
    expect(navForRoles(nav, true).map((group) => group.group)).toEqual(["MONEY", "WORK"]);
  });

  it("marks exactly the three money-governance destinations as owner-only", () => {
    const ownerOnly = ADMIN_NAV.flatMap((group) =>
      group.items.filter((item) => item.ownerOnly).map((item) => item.href),
    );
    expect(ownerOnly.sort()).toEqual(["/admin/audit-logs", "/admin/payouts", "/admin/reports"]);
  });
});

describe("isOwnerOnlyRoute", () => {
  it("flags owner-only pages and their children", () => {
    expect(isOwnerOnlyRoute("/admin/payouts")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/payouts/po-1")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/reports")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/reports/session-economics")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/reports/refunds")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/audit-logs")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/coach-payslip")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/session-economics")).toBe(true);
  });

  it("keeps dues follow-up open to admins even though it lives under /admin/reports", () => {
    expect(isOwnerOnlyRoute("/admin/reports/dues")).toBe(false);
    expect(isOwnerOnlyRoute("/admin/reports/dues/parent-1")).toBe(false);
  });

  it("does not match on a shared string prefix", () => {
    expect(isOwnerOnlyRoute("/admin/reportsmith")).toBe(false);
    expect(isOwnerOnlyRoute("/admin/payoutsx")).toBe(false);
  });

  it("leaves operations routes alone", () => {
    for (const path of [
      "/admin",
      "/admin/payments",
      "/admin/expenses",
      "/admin/billing-health",
      "/admin/settings",
      "/admin/users/new",
      "/admin/dues",
    ]) {
      expect(isOwnerOnlyRoute(path), path).toBe(false);
    }
  });
});

describe("metaForPath", () => {
  it("titles the Families list", () => {
    expect(metaForPath("/admin/families").title).toBe("Families");
    expect(metaForPath("/admin/families").breadcrumbs).toEqual(["Admin", "Money", "Families"]);
  });

  it("resolves the dynamic family billing route by its [parentId] key", () => {
    const meta = metaForPath("/admin/families/par_1");
    expect(meta.title).toBe("Family billing");
    expect(meta.breadcrumbs).toEqual(["Admin", "Money", "Families", "Family"]);
  });

  it("still appends Detail for routes without a dynamic key", () => {
    expect(metaForPath("/admin/sessions/sess_1").breadcrumbs).toEqual(["Admin", "Sessions", "Detail"]);
  });
});
