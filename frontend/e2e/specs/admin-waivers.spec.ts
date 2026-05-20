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

test.describe("admin waivers", () => {
  test("renders BFF summary counts and waiver student rows", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const requests: string[] = [];
    await stubMe(page);
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
    await stubMe(page);
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
    await expect(page.getByText("Current waiver metadata is not available from the BFF yet.")).toBeVisible();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
