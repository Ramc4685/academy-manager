/**
 * Rally admin shell smoke spec (Phase 3).
 *
 * Verifies:
 *  - Rally shell mounts (sidebar with WORK / MONEY / COMMS · OPS groups).
 *  - The 5 Phase-3 routes mount and surface their data-testid.
 *  - No app-level console errors during navigation.
 *
 * Known benign warnings allowed: Next.js dev/HMR noise, React DevTools.
 * Anything else surfaces as a test failure.
 */

import { test, expect, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const ADMIN_ROUTES = [
  { href: "/admin", testid: "admin-dashboard" },
  { href: "/admin/sessions", testid: "admin-sessions" },
  { href: "/admin/payments", testid: "admin-payments" },
  { href: "/admin/messages", testid: "admin-messages" },
] as const;

const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

function isBenign(message: string): boolean {
  return BENIGN_PATTERNS.some((re) => re.test(message));
}

async function stubAdminBff(page: Page) {
  // /api/v2/me — admin role
  await page.route("**/api/v2/me", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ADMIN_ME),
    });
  });
  // Sessions
  await page.route("**/api/v2/admin/sessions*", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  // Payments
  await page.route("**/api/v2/admin/payments*", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ payments: [] }),
    });
  });
  // Revenue (used by dashboard chart)
  await page.route("**/api/v2/admin/finance/revenue*", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ by_month: {} }),
    });
  });
  // Messages
  await page.route("**/api/v2/admin/messages*", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ messages: [] }),
    });
  });
  // Catch-all stub for other admin endpoints so empty pages don't 404
  await page.route("**/api/v2/admin/**", (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

test.describe("Rally admin shell", () => {
  test("shell renders three nav groups and dashboard mounts", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isBenign(msg.text())) {
        errors.push(msg.text());
      }
    });

    await stubAdminBff(page);
    await page.goto("/admin");

    // Wait for auth-bypass + /me round-trip + dashboard mount to fully
    // settle. Without this the React strict-mode double-mount in
    // usePersonaAuth can detach the hamburger between locator-resolve
    // and click. networkidle doesn't work here because the Next dev
    // server's HMR keeps network busy; a short explicit settle is the
    // honest answer.
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await page.waitForTimeout(500);

    // Playwright projects are mobile-only (Pixel 7 / iPhone 14), so the
    // desktop sidebar is display:none. The same three groups render
    // inside the mobile drawer — open it and assert there.
    await page.getByTestId("admin-open-drawer").click();
    const drawer = page.getByTestId("admin-mobile-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("WORK", { exact: true })).toBeVisible();
    await expect(drawer.getByText("MONEY", { exact: true })).toBeVisible();
    await expect(drawer.getByText("COMMS · OPS", { exact: true })).toBeVisible();

    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  for (const route of ADMIN_ROUTES) {
    test(`route ${route.href} mounts`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error" && !isBenign(msg.text())) {
          errors.push(msg.text());
        }
      });

      await stubAdminBff(page);
      await page.goto(route.href);
      await expect(page.getByTestId(route.testid)).toBeVisible();
      expect(errors, `App console errors on ${route.href}: ${errors.join("\n")}`).toEqual([]);
    });
  }

  test("session detail page mounts", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && !isBenign(msg.text())) {
        errors.push(msg.text());
      }
    });

    await stubAdminBff(page);

    // session detail page hits listAdminSessions(today) and looks for a match.
    // With empty fixtures it just doesn't find the session — page still mounts.
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    expect(errors, `Console errors on session detail: ${errors.join("\n")}`).toEqual([]);
  });
});
