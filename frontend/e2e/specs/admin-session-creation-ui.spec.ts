import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-session-ui-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
  await page.route("**/api/v2/admin/academy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "BLNO Badminton Academy",
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

test.describe("admin session creation and fee settings UI", () => {
  test("create session modal is sectioned, validates time range, and preserves the API payload", async ({
    page,
  }) => {
    await stubAdminShell(page);
    let createPayload: unknown = null;

    await page.route("**/api/v2/admin/sessions*", (route) => {
      const request = route.request();
      if (request.method() === "GET") return fulfillJson(route, { sessions: [] });
      if (request.method() === "POST") {
        createPayload = request.postDataJSON();
        return fulfillJson(route, {
          session_id: "session-e2e",
          coach_id: "coach-e2e",
          coach_name: "Coach E2E",
          title: "Intermediate badminton",
          location: "BLNO Court 3",
          start_at: "2026-05-29T17:00:00Z",
          end_at: "2026-05-29T18:00:00Z",
          capacity: 12,
          status: "scheduled",
          enrolled_count: 0,
          waitlist_count: 0,
        });
      }
      return route.fallback();
    });
    await page.route("**/api/v2/admin/users?role=coach", (route) =>
      fulfillJson(route, {
        users: [
          {
            user_id: "coach-e2e",
            email: "coach@example.com",
            display_name: "Coach E2E",
            role: "coach",
            status: "active",
          },
        ],
      }),
    );

    await page.goto("/admin/sessions");
    await page.getByTestId("admin-sessions-create").click();

    await expect(page.getByRole("heading", { name: "Create training session" })).toBeVisible();
    await expect(page.getByText("Session details", { exact: true })).toBeVisible();
    await expect(page.getByText("Schedule", { exact: true })).toBeVisible();
    await expect(page.getByText("Review", { exact: true })).toBeVisible();
    await expect(page.getByText("Billing uses the academy fee defaults")).toBeVisible();

    await page.getByLabel("Session name*").fill(" Intermediate badminton ");
    await page.getByLabel("Court or location*").fill(" BLNO Court 3 ");
    await page.getByLabel("Lead coach*").selectOption("coach-e2e");
    await page.getByLabel("Date*").fill("2026-05-29");
    await page.getByLabel("Starts*").fill("18:00");
    await page.getByLabel("Ends*").fill("17:00");
    await page.getByLabel("Capacity*").fill("12");
    await page.getByRole("button", { name: "Create session", exact: true }).click();

    await expect(page.getByRole("alert")).toHaveText("End time must be after start time.");
    expect(createPayload).toBeNull();

    await page.getByLabel("Starts*").fill("17:00");
    await page.getByLabel("Ends*").fill("18:00");
    await page.getByRole("button", { name: "Create session", exact: true }).click();

    await expect.poll(() => createPayload).toEqual({
      coach_id: "coach-e2e",
      title: "Intermediate badminton",
      location: "BLNO Court 3",
      start_at: "2026-05-29T17:00",
      end_at: "2026-05-29T18:00",
      capacity: 12,
    });
  });

  test("fee settings use dollars and days while patching API cents", async ({ page }) => {
    await stubAdminShell(page);
    let feePatch: unknown = null;

    await page.route("**/api/v2/admin/academy/fees", (route) => {
      const request = route.request();
      if (request.method() === "GET") {
        return fulfillJson(route, {
          default_monthly_cents: 12000,
          late_fee_cents: 1500,
          grace_days: 5,
        });
      }
      if (request.method() === "PATCH") {
        feePatch = request.postDataJSON();
        return fulfillJson(route, {
          default_monthly_cents: 12550,
          late_fee_cents: 1500,
          grace_days: 5,
        });
      }
      return route.fallback();
    });

    await page.goto("/admin/settings?panel=fees");

    await expect(page.getByRole("heading", { name: "Tuition and payment rules" })).toBeVisible();
    await expect(page.getByLabel("Default monthly tuition")).toHaveValue("120");
    await expect(page.getByLabel("Late payment fee")).toHaveValue("15");
    await expect(page.getByLabel("Payment grace period")).toHaveValue("5");
    await expect(page.getByText("Monthly cents")).toHaveCount(0);

    await page.getByLabel("Default monthly tuition").fill("125.50");
    await page.getByRole("button", { name: "Save billing defaults" }).click();

    await expect.poll(() => feePatch).toEqual({ default_monthly_cents: 12550 });
  });
});
