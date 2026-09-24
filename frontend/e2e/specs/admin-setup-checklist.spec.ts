import { test, expect, type Page } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

/**
 * Roadmap L7: the dashboard's "Set up your academy" card. Completion is
 * decided by the BFF from existing settings; the card lists open steps
 * first, links each to where it is done, and disappears once complete.
 * Every API is stubbed; names are fake.
 */

type Status = "done" | "todo" | "unknown";

function step(key: string, label: string, status: Status, href: string, ownerOnly = false) {
  return { key, label, detail: `${label} detail.`, status, href, owner_only: ownerOnly };
}

function checklist(statuses: Partial<Record<string, Status>> = {}) {
  const items = [
    step("academy_profile", "Academy details", statuses.academy_profile ?? "done", "/admin/settings?panel=academy"),
    step("branding", "Branding", statuses.branding ?? "todo", "/admin/settings?panel=branding"),
    step("billing_rules", "Billing rules", statuses.billing_rules ?? "done", "/admin/settings?panel=billing-rules", true),
    step("stripe_connect", "Card payments", statuses.stripe_connect ?? "todo", "/admin/settings?panel=gateway", true),
    step("session_types", "Session types", statuses.session_types ?? "done", "/admin/settings?panel=session-types"),
    step("classes", "First classes", statuses.classes ?? "todo", "/admin/sessions"),
    step("staff", "Invite your team", statuses.staff ?? "done", "/admin/users"),
    step("waiver", "Waiver", statuses.waiver ?? "unknown", "/admin/waivers"),
    step("public_page", "Public class page", statuses.public_page ?? "done", "/admin/settings?panel=public-page"),
  ];
  const done = items.filter((row) => row.status === "done").length;
  return { items, done_count: done, total: items.length, complete: done === items.length };
}

async function setup(page: Page, body: unknown) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
    fulfillJson(route, { items: [] }),
  );
  await page.route("**/api/v2/admin/sessions*", (route) => fulfillJson(route, { sessions: [] }));
  await page.route("**/api/v2/admin/follow-ups*", (route) =>
    fulfillJson(route, { follow_ups: [] }),
  );
  const calls: string[] = [];
  await page.route("**/api/v2/admin/setup-checklist", (route) => {
    calls.push(route.request().method());
    return fulfillJson(route, body);
  });
  return { errors, calls };
}

test.describe("admin setup checklist", () => {
  test("lists open steps first and links each to where it is done", async ({ page }) => {
    const { errors, calls } = await setup(page, checklist());
    await page.goto("/admin");

    const card = page.getByTestId("dashboard-setup-checklist");
    await expect(card).toBeVisible();
    await expect(page.getByTestId("dashboard-setup-checklist-progress")).toHaveText(
      "5 of 9 steps done",
    );
    const keys = await card
      .locator("li[data-testid^='setup-step-']")
      .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-testid")));
    expect(keys.slice(0, 4)).toEqual([
      "setup-step-branding",
      "setup-step-stripe_connect",
      "setup-step-classes",
      "setup-step-waiver",
    ]);
    await expect(page.getByTestId("setup-step-waiver")).toContainText("COULDN'T CHECK");
    await expect(page.getByTestId("setup-step-stripe_connect").getByRole("link")).toHaveAttribute(
      "href",
      "/admin/settings?panel=gateway",
    );

    await page.getByTestId("setup-step-branding").getByRole("link").click();
    await expect(page).toHaveURL(/\/admin\/settings\?panel=branding/);
    expect(calls.every((method) => method === "GET")).toBe(true);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("disappears once every step is done", async ({ page }) => {
    const all = Object.fromEntries(
      checklist().items.map((row) => [row.key, "done" as Status]),
    );
    const { errors } = await setup(page, checklist(all));
    await page.goto("/admin");

    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await expect(page.getByTestId("dashboard-my-follow-ups")).toBeVisible();
    await expect(page.getByTestId("dashboard-setup-checklist")).toHaveCount(0);
    expect(errors, errors.join("\n")).toEqual([]);
  });
});
