import { describe, expect, it } from "vitest";

import { Icon } from "../ds/icons";
import {
  ADMIN_NAV,
  OWNER_ONLY_ROUTE_EXCEPTIONS,
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

  // #839: Students, Users and Families all shipped `icon: "user"`, so the
  // three People destinations were indistinguishable in the sidebar.
  it("gives Students, Users and Families three distinct icons", () => {
    const items = ADMIN_NAV.flatMap((group) => group.items);
    const iconFor = (href: string) => items.find((item) => item.href === href)?.icon;
    const icons = [
      iconFor("/admin/students"),
      iconFor("/admin/users"),
      iconFor("/admin/families"),
    ];

    expect(icons.every(Boolean)).toBe(true);
    expect(new Set(icons).size).toBe(3);
  });

  it("removes a group whose every item was owner-only", () => {
    const nav: AdminNavGroup[] = [
      {
        group: "MONEY",
        items: [
          { id: "reports", href: "/admin/reports", label: "Reports", icon: "chart", match: () => false, ownerOnly: true },
        ],
      },
      {
        group: "WORK",
        items: [{ id: "dashboard", href: "/admin", label: "Dashboard", icon: "home", match: () => false }],
      },
    ];
    expect(navForRoles(nav, false).map((group) => group.group)).toEqual(["WORK"]);
    expect(navForRoles(nav, true).map((group) => group.group)).toEqual(["MONEY", "WORK"]);
  });

  it("marks exactly the money-governance destinations as owner-only", () => {
    const ownerOnly = ADMIN_NAV.flatMap((group) =>
      group.items.filter((item) => item.ownerOnly).map((item) => item.href),
    );
    // Billing Health joined this list with the trim (spec 2026-09-07 §2):
    // Stripe plumbing is governance, the same tier as Reports and Payouts.
    expect(ownerOnly.sort()).toEqual([
      "/admin/audit-logs",
      "/admin/billing-health",
      "/admin/payouts",
      "/admin/reports",
    ]);
  });
});

// Sidebar regroup spec §2 / §6 PR 1.
describe("ADMIN_NAV shape", () => {
  const items = ADMIN_NAV.flatMap((group) => group.items);

  it("has the six groups in sidebar order", () => {
    expect(ADMIN_NAV.map((group) => group.group)).toEqual([
      "TODAY",
      "CLASSES",
      "PEOPLE",
      "REACH",
      "MONEY",
      "ACADEMY",
    ]);
  });

  it("gives every item a unique, testid-safe id", () => {
    const ids = items.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });

  it("keeps the ids the e2e specs address as admin-nav-<id>", () => {
    // These were once derived from the label; they are pinned here so a
    // relabel (Users -> Staff in PR 3) cannot move a testid.
    const byHref = Object.fromEntries(items.map((item) => [item.href, item.id]));
    expect(byHref).toMatchObject({
      "/admin/students": "students",
      "/admin/inbox": "inbox",
      "/admin/users": "users",
      "/admin/payments": "payments",
      "/admin/expenses": "expenses",
      "/admin/reports": "month-close",
      "/admin/payouts": "coach-payouts",
      "/admin/billing-health": "billing-health",
      "/admin/audit-logs": "audit-logs",
    });
  });

  it("uses only icon keys the Rally Icon set implements", () => {
    // renderNavIcon falls back to `home` for an unknown key, so a typo would
    // silently show a house; pin it here instead.
    for (const item of items) {
      expect(typeof Icon[item.icon], `${item.href} -> ${item.icon}`).toBe("function");
    }
  });

  it("gives Waivers its own glyph rather than sharing Inbox's", () => {
    const iconFor = (href: string) => items.find((item) => item.href === href)?.icon;
    expect(iconFor("/admin/waivers")).toBe("attend");
    expect(iconFor("/admin/waivers")).not.toBe(iconFor("/admin/inbox"));
    expect(iconFor("/admin/users")).toBe("badge");
  });

  it("places the people lists together and Inbox under Dashboard", () => {
    const groupOf = (href: string) =>
      ADMIN_NAV.find((group) => group.items.some((item) => item.href === href))?.group;
    expect(groupOf("/admin/inbox")).toBe("TODAY");
    expect(groupOf("/admin/students")).toBe("PEOPLE");
    expect(groupOf("/admin/families")).toBe("PEOPLE");
    expect(groupOf("/admin/users")).toBe("PEOPLE");
    expect(groupOf("/admin/messages")).toBe("REACH");
    expect(groupOf("/admin/waivers")).toBe("ACADEMY");
  });

  it("still shows all six groups to a non-owner", () => {
    expect(navForRoles(ADMIN_NAV, false).map((group) => group.group)).toEqual(
      ADMIN_NAV.map((group) => group.group),
    );
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
    expect(isOwnerOnlyRoute("/admin/billing-health")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/coach-payslip")).toBe(true);
    expect(isOwnerOnlyRoute("/admin/session-economics")).toBe(true);
  });

  it("keeps the old Dues path reachable so its redirect can run for admins", () => {
    // The page is gone, but the path is now a redirect to `/admin/payments` —
    // a page admins may use. Dropping the exception would meet an admin
    // following an old bookmark with an owner-only wall instead of forwarding
    // them (month close spec §6).
    expect(OWNER_ONLY_ROUTE_EXCEPTIONS).toEqual(["/admin/reports/dues"]);
    expect(isOwnerOnlyRoute("/admin/reports/dues")).toBe(false);
    expect(isOwnerOnlyRoute("/admin/reports")).toBe(true);
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
    // Reports is Month close now (spec §5); the sub-reports say so too.
    expect(metaForPath("/admin/reports").title).toBe("Month close");
    expect(metaForPath("/admin/reports").breadcrumbs).toEqual(["Admin", "Money", "Month close"]);
    expect(metaForPath("/admin/reports/deposit-slip").breadcrumbs).toEqual([
      "Admin",
      "Money",
      "Month close",
      "Deposit slip",
    ]);
    // Families moved from MONEY to PEOPLE (sidebar regroup spec §2.2 row 6).
    expect(metaForPath("/admin/families").breadcrumbs).toEqual(["Admin", "People", "Families"]);
  });

  it("resolves the dynamic family billing route by its [parentId] key", () => {
    const meta = metaForPath("/admin/families/par_1");
    expect(meta.title).toBe("Family");
    expect(meta.breadcrumbs).toEqual(["Admin", "People", "Families", "Family"]);
  });

  it("still appends Detail for routes without a dynamic key", () => {
    expect(metaForPath("/admin/sessions/sess_1").breadcrumbs).toEqual(["Admin", "Sessions", "Detail"]);
  });
});
