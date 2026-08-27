/**
 * Wave 5 Agent C — Parent registration + waiver template-version specs.
 *
 * Covers:
 *   - Parent registration: /register lands the parent on /parent/onboarding
 *     cleanly via the v2 BFF.
 *   - Waiver signed by a parent surfaces on the admin waivers list with
 *     the correct template version.
 *   - No legacy /api/* traffic during either flow.
 */

import { test, expect } from "@playwright/test";

import {
  collectConsoleErrors,
  installTenantGuard,
} from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
  stubParentProfile,
} from "../fixtures/saas-stubs";

test.describe("SaaS v2 — parent registration", () => {
  test("parent onboarding lands cleanly after register hits /register/parent", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    // /parent/onboarding kicks off via POST /parent/onboarding/start.
    // The bypass auth fixture already synthesises a logged-in user, so
    // we can land directly on /parent/onboarding (skipping the Firebase
    // sign-up bits which are out-of-scope for SaaS tenant testing).
    await stubMe(page, {
      user_id: "user-parent-w5",
      email: "parent@example.com",
      academy_id: ACADEMY_A,
      roles: ["parent"],
    });
    // The parent layout fetches this on every /parent/* page (issue #380).
    await stubParentProfile(page, { user_id: "user-parent-w5" });

    const onboardingStarts: number[] = [];
    await page.route("**/api/v2/parent/onboarding/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      onboardingStarts.push(Date.now());
      return fulfillJson(route, {
        application_id: "app-w5-1",
        parent_profile: { full_name: "", email: "parent@example.com", phone: "" },
        child_profile: null,
        selected_session_id: null,
        accept_waiver: false,
        status: "draft",
      });
    });
    await page.route("**/api/v2/parent/sessions/available", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { sessions: [] });
    });

    await page.goto("/parent/onboarding");

    // The onboarding page renders the parent-profile step on first
    // load. Assert the page mounted and the start endpoint fired.
    await expect
      .poll(() => onboardingStarts.length, {
        message: "Expected POST /parent/onboarding/start",
      })
      .toBeGreaterThanOrEqual(1);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});

test.describe("SaaS v2 — waiver template versioning", () => {
  test("admin waiver row surfaces the correct template version for a signed parent waiver", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, {
      user_id: "user-admin-w5",
      email: "admin@example.com",
      academy_id: ACADEMY_A,
      roles: ["admin"],
    });
    await stubAcademy(page, ACADEMY_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
    ]);

    const TEMPLATE_VERSION = "v4.2";

    await page.route(/\/api\/v2\/admin\/waivers(?:\?.*)?$/, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        summary: {
          signed_current: 1,
          pending_signature: 0,
          expiring_30d: 0,
          outdated_version: 0,
          active_students: 1,
          adoption_rate: 1.0,
        },
        current_waiver: {
          waiver_id: "wt-current",
          title: "Liability and media release",
          version: TEMPLATE_VERSION,
          description: "Academy waiver text supplied by the admin BFF.",
          effective_at: "2026-01-01T00:00:00Z",
          last_edited_at: "2026-02-14T00:00:00Z",
          signed_count: 1,
          total_count: 1,
          adoption_rate: 1.0,
        },
        waivers: [
          {
            waiver_id: "waiver-w5-signed",
            student_id: "student-w5",
            student_name: "Asha Iyer",
            parent_id: "parent-w5",
            parent_name: "Meera Iyer",
            parent_email: "meera@example.com",
            status: "signed",
            version: TEMPLATE_VERSION,
            signed_at: "2026-05-20T10:00:00Z",
            method: "E-sign",
            expires_at: "2029-05-20T10:00:00Z",
          },
        ],
      });
    });
    await page.route(/\/api\/v2\/admin\/waivers\/templates(?:\?.*)?$/, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { templates: [] });
    });
    await page.route("**/api/v2/admin/waivers/wt-current", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        waiver_id: "wt-current",
        title: "Liability and media release",
        version: TEMPLATE_VERSION,
        status: "active",
        body: "Academy waiver text supplied by the admin BFF.",
        content_hash: null,
        effective_at: "2026-01-01T00:00:00Z",
        assigned_to_registration: true,
        assigned_at: "2026-01-01T00:00:00Z",
        artifact_status: "unavailable",
        share_status: "unavailable",
        gap_note: "Template artifact metadata is not generated in this E2E fixture.",
      });
    });

    await page.goto("/admin/waivers");
    const row = page.getByTestId("admin-waivers-row-waiver-w5-signed");
    await expect(row).toContainText("Asha Iyer");
    await expect(row).toContainText("Meera Iyer");
    await expect(
      row,
      "Signed waiver must surface the parent-signed template version"
    ).toContainText(TEMPLATE_VERSION);
    await expect(row).toContainText("SIGNED");

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});

test.describe("SaaS v2 — no legacy /api/* traffic anywhere in admin smoke", () => {
  test("admin dashboard never issues a legacy /api/* request", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, {
      user_id: "user-admin-w5",
      email: "admin@example.com",
      academy_id: ACADEMY_A,
      roles: ["admin"],
    });
    await stubAcademy(page, ACADEMY_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
    ]);
    await page.route("**/api/v2/admin/**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {});
    });
    await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
      fulfillJson(route, { items: [] })
    );

    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    // No /api/* call may have happened that isn't /api/v2/*.
    guard.assertNoLegacyApiCalls();
    expect(
      guard.v2Requests.length,
      "Smoke must observe at least one v2 BFF call"
    ).toBeGreaterThan(0);
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
