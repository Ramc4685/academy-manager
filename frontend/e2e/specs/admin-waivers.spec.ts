import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-waivers-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

function isBenign(message: string): boolean {
  return BENIGN_PATTERNS.some((re) => re.test(message));
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isBenign(msg.text())) {
      errors.push(msg.text());
    }
  });
  return errors;
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubMe(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
}

async function stubAdminShell(page: Page) {
  await stubMe(page);
  await page.route("**/api/v2/admin/academy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Rally Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    });
  });
}

async function stubWaiverTemplates(page: Page) {
  await page.route("**/api/v2/admin/waivers/templates*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { templates: [] });
  });
}

test.describe("admin waivers", () => {
  test("renders BFF summary counts and waiver student rows", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const requests: string[] = [];
    await stubAdminShell(page);
    await stubWaiverTemplates(page);
    await page.route("**/api/v2/admin/waivers*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      requests.push(route.request().url());
      return fulfillJson(route, {
        summary: {
          signed_current: 12,
          pending_signature: 2,
          expiring_30d: 1,
          outdated_version: 3,
          active_students: 18,
          adoption_rate: 0.67,
        },
        current_waiver: {
          title: "Liability and media release",
          version: "v3.1",
          description: "Current academy waiver text supplied by the admin BFF.",
          effective_at: "2024-01-01T00:00:00Z",
          last_edited_at: "2024-02-14T00:00:00Z",
          signed_count: 12,
          total_count: 18,
          adoption_rate: 0.67,
        },
        waivers: [
          {
            waiver_id: "waiver-signed",
            student_id: "student-1",
            student_name: "Aarav Sharma",
            parent_id: "parent-1",
            parent_name: "Rohan Sharma",
            parent_email: "rohan@example.com",
            status: "signed",
            version: "v3.1",
            signed_at: "2024-02-12T12:00:00Z",
            method: "E-sign",
            expires_at: "2027-02-12T12:00:00Z",
          },
          {
            waiver_id: "waiver-pending",
            student_id: "student-2",
            student_name: "Vivaan Bhat",
            parent_id: "parent-2",
            parent_name: "Lakshmi Bhat",
            parent_email: "lakshmi@example.com",
            status: "pending",
            version: "v3.1",
            signed_at: null,
            method: null,
            expires_at: null,
          },
        ],
      });
    });

    await page.goto("/admin/waivers");

    await expect(page.getByTestId("admin-waivers")).toBeVisible();
    await expect(page.getByText("Signed current")).toBeVisible();
    await expect(page.getByText("67% of active students").first()).toBeVisible();
    await expect(page.getByText("Pending signature")).toBeVisible();
    await expect(page.getByText("Expiring 30d")).toBeVisible();
    await expect(page.getByText("Outdated version")).toBeVisible();
    await expect(page.getByText("Liability and media release")).toBeVisible();

    const signedRow = page.getByTestId("admin-waivers-row-waiver-signed");
    await expect(signedRow).toContainText("Aarav Sharma");
    await expect(signedRow).toContainText("Rohan Sharma");
    await expect(signedRow).toContainText("v3.1");
    await expect(signedRow).toContainText("SIGNED");

    const pendingRow = page.getByTestId("admin-waivers-row-waiver-pending");
    await expect(pendingRow).toContainText("Vivaan Bhat");
    await expect(pendingRow).toContainText("PENDING");
    expect(requests).toHaveLength(1);
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("shows a truthful empty state when the BFF returns no waiver rows", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await stubWaiverTemplates(page);
    await page.route("**/api/v2/admin/waivers*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
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
      });
    });

    await page.goto("/admin/waivers");
    await expect(page.getByTestId("admin-waivers-empty")).toContainText("No waiver rows returned.");
    await expect(page.getByText("Current waiver details are not available yet.")).toBeVisible();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("renders signed waiver artifact and share references", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/waivers/signatures/ws-1", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        signature_id: "ws-1",
        student_name: "Aarav Sharma",
        parent_name: "Rohan Sharma",
        parent_email: "rohan@example.com",
        signed_at: "2026-05-01T12:00:00Z",
        signer_name: "Rohan Sharma",
        signer_email: "rohan@example.com",
        waiver_title: "Annual waiver",
        waiver_version: "2026.1",
        template_reference: "wt-2026",
        content_hash: "hash-current",
        artifact_reference: "wa_ws-1",
        share_link_reference: "wsl_non_guessable_token_for_test",
        artifact_status: "stored",
        share_status: "available",
        gap_note: "Signed waiver artifact metadata is stored and an authorized share link is active.",
      });
    });

    await page.goto("/admin/waivers/signatures/ws-1");

    await expect(page.getByTestId("admin-signed-waiver-detail")).toBeVisible();
    await expect(page.getByText("Aarav Sharma")).toBeVisible();
    await expect(page.locator("dd").filter({ hasText: /^Stored$/ })).toBeVisible();
    await expect(page.locator("dd").filter({ hasText: /^Available$/ })).toBeVisible();
    await expect(page.getByText("wa_ws-1")).toBeVisible();
    await expect(page.getByText("wsl_non_guessable_token_for_test")).toBeVisible();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("allows requiring an active waiver from the detail page", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const assignmentRequests: string[] = [];
    let detailRequests = 0;
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/waivers/wt-2026", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      detailRequests += 1;
      if (detailRequests > 1) {
        return fulfillJson(route, { detail: "temporary refetch failure" }, 500);
      }
      return fulfillJson(route, {
        waiver_id: "wt-2026",
        title: "BLNO Liability Waiver",
        version: "1.0",
        body: "Parent agrees to academy safety rules.",
        content_hash: "hash-current",
        effective_at: "2026-05-26T00:00:00Z",
        status: "active",
        assigned_to_registration: false,
        assigned_at: null,
        artifact_status: "unavailable",
        share_status: "unavailable",
        gap_note: "Signed PDF artifact/share links are not implemented yet.",
      });
    });
    await page.route("**/api/v2/admin/waivers/templates/wt-2026/assign-registration", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      assignmentRequests.push(route.request().url());
      return fulfillJson(route, {
        waiver_template_id: "wt-2026",
        title: "BLNO Liability Waiver",
        body: "Parent agrees to academy safety rules.",
        status: "active",
        version: "1.0",
        content_hash: "hash-current",
        effective_at: "2026-05-26T00:00:00Z",
        published_at: "2026-05-26T00:00:00Z",
        assigned_to_registration: true,
        assigned_at: "2026-06-21T12:00:00Z",
        updated_at: "2026-06-21T12:00:00Z",
      });
    });

    await page.goto("/admin/waivers/wt-2026");

    await expect(page.getByTestId("admin-waiver-template-detail")).toBeVisible();
    await expect(page.getByText("Not assigned").first()).toBeVisible();
    await page.getByRole("button", { name: "Require for registration" }).click();
    await expect(page.getByText("Required for registration").first()).toBeVisible();
    await expect(
      page.getByRole("alert").filter({ hasText: "Could not load waiver template." }),
    ).toHaveCount(0);
    expect(assignmentRequests).toHaveLength(1);
    expect(
      errors.filter((message) => !message.includes("500 (Internal Server Error)")),
      `App console errors: ${errors.join("\n")}`,
    ).toEqual([]);
  });
});
