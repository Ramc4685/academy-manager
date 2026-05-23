/**
 * Wave 12 launch-candidate route matrix scaffold.
 *
 * This is intentionally network-stubbed. Final smoke against the real local
 * SaaS stack waits for Wave 10 and Wave 11 branches to merge.
 */

import { test, expect, type Page } from "@playwright/test";

import {
  collectConsoleErrors,
  installTenantGuard,
} from "../fixtures/tenant-isolation";
import { ACADEMY_A, fulfillJson, stubMe } from "../fixtures/saas-stubs";

const ADMIN_ME = {
  user_id: "user-admin-wave12",
  email: "admin@blno-badminton.dev",
  academy_id: ACADEMY_A,
  roles: ["admin" as const],
};

const COACH_ME = {
  user_id: "user-coach-wave12",
  email: "coach@blno-badminton.dev",
  academy_id: ACADEMY_A,
  roles: ["coach" as const],
};

const PARENT_ME = {
  user_id: "user-parent-wave12",
  email: "parent@blno-badminton.dev",
  academy_id: ACADEMY_A,
  roles: ["parent" as const],
};

const ADMIN_ROUTE_MATRIX = [
  { label: "admin dashboard", href: "/admin", testId: "admin-dashboard" },
  { label: "sessions", href: "/admin/sessions", testId: "admin-sessions" },
  { label: "students", href: "/admin/students", testId: "admin-students" },
  { label: "users", href: "/admin/users", testId: "admin-users" },
  { label: "waitlist", href: "/admin/waitlist", testId: "admin-waitlist" },
  {
    label: "pause requests",
    href: "/admin/pause-requests",
    testId: "admin-pause-requests",
  },
  { label: "payments", href: "/admin/payments", testId: "admin-payments" },
  { label: "dues", href: "/admin/dues", testId: "admin-dues" },
  { label: "expenses", href: "/admin/expenses", testId: "admin-expenses" },
  { label: "payouts", href: "/admin/payouts", testId: "admin-payouts" },
  { label: "reports", href: "/admin/reports", testId: "admin-reports" },
  { label: "messages", href: "/admin/messages", testId: "admin-messages" },
  { label: "waivers", href: "/admin/waivers", testId: "admin-waivers" },
  { label: "settings", href: "/admin/settings", testId: "admin-settings-academy" },
  { label: "audit logs", href: "/admin/audit-logs", testId: "admin-audit-logs" },
] as const;

async function stubAdminLaunchBff(page: Page): Promise<void> {
  await stubMe(page, ADMIN_ME);

  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });

  await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
    fulfillJson(route, { items: [] })
  );
  await page.route("**/api/v2/admin/sessions*", (route) =>
    fulfillJson(route, { sessions: [] })
  );
  await page.route("**/api/v2/admin/students*", (route) =>
    fulfillJson(route, { students: [], next_cursor: null })
  );
  await page.route("**/api/v2/admin/users*", (route) =>
    fulfillJson(route, { users: [] })
  );
  await page.route("**/api/v2/admin/waitlist", (route) =>
    fulfillJson(route, { total_waitlisted: 0, sessions: [] })
  );
  await page.route("**/api/v2/admin/pause-requests*", (route) =>
    fulfillJson(route, { requests: [] })
  );
  await page.route("**/api/v2/admin/payments*", (route) =>
    fulfillJson(route, { payments: [] })
  );
  await page.route("**/api/v2/admin/dues-followup*", (route) =>
    fulfillJson(route, { parents: [] })
  );
  await page.route("**/api/v2/admin/finance/expenses*", (route) =>
    fulfillJson(route, { expenses: [] })
  );
  await page.route("**/api/v2/admin/finance/payouts*", (route) =>
    fulfillJson(route, { payouts: [] })
  );
  await page.route("**/api/v2/admin/finance/revenue*", (route) =>
    fulfillJson(route, { by_month: {} })
  );
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [] })
  );
  await page.route("**/api/v2/admin/waivers*", (route) =>
    fulfillJson(route, {
      summary: {
        signed_current: 0,
        pending_signature: 0,
        expiring_30d: 0,
        outdated_version: 0,
        active_students: 0,
        adoption_rate: null,
      },
      current_waiver: null,
      waivers: [],
    })
  );
  await page.route("**/api/v2/admin/audit-logs*", (route) =>
    fulfillJson(route, { logs: [] })
  );
  await page.route(/\/api\/v2\/admin\/academy\/fees(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      default_monthly_cents: null,
      late_fee_cents: null,
      grace_days: null,
    })
  );
  await page.route(/\/api\/v2\/admin\/academy\/gateway(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      stripe_connected: false,
      stripe_account_id_masked: null,
      manual_methods: ["cash", "check"],
    })
  );
  await page.route(
    /\/api\/v2\/admin\/academy\/notifications(?:\?.*)?$/,
    (route) =>
      fulfillJson(route, {
        dues_reminders: false,
        attendance_alerts: false,
        daily_digest_to_admin: false,
      })
  );
  await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      academy_id: ACADEMY_A,
      display_name: "BLNO Badminton Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    })
  );
}

async function stubCoachLaunchBff(page: Page): Promise<void> {
  await stubMe(page, COACH_ME);
  await page.route("**/api/v2/coach/today*", (route) =>
    fulfillJson(route, { date: "2026-05-22", sessions: [] })
  );
}

async function stubParentLaunchBff(page: Page): Promise<void> {
  await stubMe(page, PARENT_ME);
  await page.route("**/api/v2/parent/payments", (route) =>
    fulfillJson(route, { payments: [] })
  );
  await page.route("**/api/v2/parent/enrollments", (route) =>
    fulfillJson(route, { enrollments: [] })
  );
  await page.route("**/api/v2/parent/pause-requests", (route) =>
    fulfillJson(route, { requests: [] })
  );
  await page.route("**/api/v2/parent/credits", (route) =>
    fulfillJson(route, { balance_cents: 0, credits: [] })
  );
}

test.describe("Wave 12 SaaS launch route matrix scaffold", () => {
  for (const route of ADMIN_ROUTE_MATRIX) {
    test(`admin route mounts: ${route.label}`, async ({ page }) => {
      const guard = installTenantGuard(page);
      const errors = collectConsoleErrors(page);

      await stubAdminLaunchBff(page);
      await page.goto(route.href);

      await expect(page.getByTestId(route.testId)).toBeVisible({ timeout: 15_000 });
      expect(guard.v2Requests.length).toBeGreaterThan(0);
      guard.assertNoLegacyApiCalls();
      expect(errors, `Console errors on ${route.href}: ${errors.join("\n")}`).toEqual([]);
    });
  }

  test("coach today route mounts", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubCoachLaunchBff(page);
    await page.goto("/coach/today");

    await expect(page.getByTestId("coach-today")).toBeVisible();
    expect(guard.v2Requests.length).toBeGreaterThan(0);
    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors on /coach/today: ${errors.join("\n")}`).toEqual([]);
  });

  test("parent payments route mounts", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubParentLaunchBff(page);
    await page.goto("/parent/payments");

    await expect(page.getByTestId("parent-payments")).toBeVisible();
    expect(guard.v2Requests.length).toBeGreaterThan(0);
    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors on /parent/payments: ${errors.join("\n")}`).toEqual([]);
  });
});
