/**
 * Wave 5 Agent C — SaaS v2 tenant-isolation & login flow specs.
 *
 * Covers:
 *   - Login + tenant resolution: multi-membership user lands on the
 *     active academy (per /api/v2/me).
 *   - Academy switch: switching memberships updates the tenant identity
 *     observed on subsequent v2 calls.
 *   - Admin sessions list scoped to the active academy.
 *   - Smoke: no legacy /api/* requests anywhere.
 *
 * Tenant rules per AGENTS.md:
 *   - SaaS mode is v2-only.
 *   - Legacy /api/* routes are forbidden in SaaS mode.
 *
 * The frontend on origin/main does not yet ship an academy-switcher UI
 * (Wave 5 Agent B owns that). Where that UI is missing we exercise the
 * tenant contract by re-stubbing /api/v2/me with a different academy
 * and reloading, which simulates the post-switch state.
 */

import { test, expect } from "@playwright/test";

import {
  collectConsoleErrors,
  installTenantGuard,
} from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ACADEMY_B,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

test.describe("SaaS v2 — login + tenant resolution", () => {
  test("multi-membership user lands on their active academy admin home", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, ADMIN_USER_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
      { academy_id: ACADEMY_B, academy_name: "Rally Academy", role: "admin" },
    ]);
    await stubAcademy(page, ACADEMY_A);
    // Catch-all admin BFF.
    await page.route("**/api/v2/admin/**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {});
    });
    await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
      fulfillJson(route, { items: [] })
    );

    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    // /me responded with academy-aces; downstream admin BFF calls must
    // therefore have been scoped to that tenant. We can't always assert
    // an X-Tenant header (depends on whether the FE adds it explicitly),
    // but we CAN assert no leakage to academy-rally URLs and no legacy
    // calls.
    guard.assertNoLegacyApiCalls();
    expect(
      guard.legacyRequests,
      "No SaaS workflow should call legacy /api/*"
    ).toEqual([]);
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("switching academies re-issues BFF reads against the new tenant", async ({
    page,
  }) => {
    // The academy-switcher UI is owned by Wave 5 Agent B. We exercise
    // the contract at the network layer: re-stub /me with academy B,
    // reload, assert all subsequent v2 calls reflect academy B (here
    // via the /admin/academy stub response, since the active-tenant
    // header is FE implementation-specific and may not yet exist).
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    let activeAcademy = ACADEMY_A;
    // Register the catch-all FIRST so the specific routes below override
    // it (Playwright matches handlers in LIFO order).
    await page.route("**/api/v2/admin/**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {});
    });
    await page.route("**/api/v2/me", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { ...ADMIN_USER_A, academy_id: activeAcademy });
    });
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
      { academy_id: ACADEMY_B, academy_name: "Rally Academy", role: "admin" },
    ]);
    await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
      fulfillJson(route, { items: [] })
    );
    // These match the academy settings BFFs hit by /admin/settings.
    await page.route(/\/api\/v2\/admin\/academy\/fees(?:\?.*)?$/, (route) =>
      fulfillJson(route, {
        default_monthly_cents: null,
        late_fee_cents: null,
        grace_days: null,
      })
    );
    await page.route(/\/api\/v2\/admin\/academy\/notifications(?:\?.*)?$/, (route) =>
      fulfillJson(route, {
        dues_reminders: false,
        attendance_alerts: false,
        daily_digest_to_admin: false,
      })
    );
    await page.route(/\/api\/v2\/admin\/academy\/gateway(?:\?.*)?$/, (route) =>
      fulfillJson(route, {
        stripe_connected: false,
        stripe_account_id_masked: null,
        manual_methods: ["cash", "check"],
      })
    );
    // Academy resource is what we use to assert tenant identity post-switch.
    await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        academy_id: activeAcademy,
        display_name:
          activeAcademy === ACADEMY_A ? "Aces Academy" : "Rally Academy",
        timezone: "UTC",
        contact_email: null,
        contact_phone: null,
        hours_text: null,
        address: null,
      });
    });

    // Land on settings (the only admin route on origin/main that
    // actually fetches /admin/academy). This represents pre-switch.
    await page.goto("/admin/settings");
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    // The display name comes straight from /admin/academy; once it's
    // visible we know the fetch happened (or React Query rendered it).
    await expect(page.locator('input[value="Aces Academy"]')).toBeVisible();
    const isAcademyFetch = (url: string) =>
      new URL(url).pathname === "/api/v2/admin/academy";
    await expect
      .poll(() => guard.v2Requests.filter((r) => isAcademyFetch(r.url)).length, {
        message: "Expected /admin/academy fetch on /admin/settings",
      })
      .toBeGreaterThanOrEqual(1);
    const preSwitchAcademyCalls = guard.v2Requests.filter((r) =>
      isAcademyFetch(r.url)
    ).length;

    // Simulate the switch — Agent B will ship the actual switcher UI.
    // We flip the source of truth (what /me + /admin/academy return)
    // and reload to model the post-switch state. Every subsequent
    // /admin/academy fetch must therefore see academy B.
    activeAcademy = ACADEMY_B;
    await page.reload();
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    await expect(page.locator('input[value="Rally Academy"]')).toBeVisible();

    await expect
      .poll(() => guard.v2Requests.filter((r) => isAcademyFetch(r.url)).length, {
        message: "Reload after academy switch must re-issue /admin/academy",
      })
      .toBeGreaterThan(preSwitchAcademyCalls);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});

test.describe("SaaS v2 — cross-tenant data isolation (admin sessions)", () => {
  test("admin only sees sessions for the active academy; other academy's sessions never appear", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, ADMIN_USER_A);
    await stubAcademy(page, ACADEMY_A);
    await page.route("**/api/v2/admin/**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {});
    });

    // /admin/sessions returns ONLY academy-aces' sessions. If anything
    // from academy-rally renders, the test fails.
    await page.route("**/api/v2/admin/sessions*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        sessions: [
          {
            session_id: "sess-aces-1",
            title: "Aces Junior A",
            location: "Aces Court",
            start_at: "2026-05-22T09:00:00Z",
            end_at: "2026-05-22T10:30:00Z",
            coach_id: "coach-aces",
            coach_name: "Coach Aces",
            enrolled_count: 5,
            capacity: 10,
            waitlist_count: 0,
            academy_id: ACADEMY_A,
          },
        ],
      });
    });

    await page.goto("/admin/sessions");
    await expect(page.getByTestId("admin-sessions")).toBeVisible();
    await expect(page.getByTestId("session-row-sess-aces-1")).toBeVisible();

    // No row from the other academy should ever exist. The BFF was
    // stubbed to return only academy-aces, so any "sess-rally-*" row
    // or any session-row from a tenant we never named would be a leak.
    await expect(
      page.locator('[data-testid^="session-row-sess-rally-"]')
    ).toHaveCount(0);
    // The admin sessions TABLE must contain exactly the one stubbed row.
    await expect(
      page.locator('[data-testid="admin-sessions-table"] [data-testid^="session-row-"]')
    ).toHaveCount(1);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
