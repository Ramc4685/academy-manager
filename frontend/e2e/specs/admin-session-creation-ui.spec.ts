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
  test("create session dialog opens, fills form, and preserves the API payload", async ({
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
          days_of_week: ["Fri"],
          start_time: "17:00",
          end_time: "18:00",
          timezone: "America/Chicago",
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

    await expect(page.getByRole("heading", { name: "Create session" })).toBeVisible();

    await page.getByLabel("Coach").selectOption("coach-e2e");
    await page.getByLabel("Name").fill("Intermediate badminton");
    await page.getByLabel("Location").fill("BLNO Court 3");
    await page.getByLabel("Day of week").selectOption("Fri");
    await page.getByLabel("Start time").fill("17:00");
    await page.getByLabel("End time").fill("18:00");
    await page.getByLabel("Capacity").fill("12");
    await page.getByRole("button", { name: "Create" }).click();

    await expect.poll(() => createPayload).toEqual({
      coach_id: "coach-e2e",
      title: "Intermediate badminton",
      location: "BLNO Court 3",
      days_of_week: ["Fri"],
      start_time: "17:00",
      end_time: "18:00",
      timezone: "America/Chicago",
      capacity: 12,
    });
  });

  test("fee settings display raw cents and days, patch only changed fields", async ({ page }) => {
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

    await expect(page.getByLabel("Monthly cents")).toHaveValue("12000");
    await expect(page.getByLabel("Late fee cents")).toHaveValue("1500");
    await expect(page.getByLabel("Grace days")).toHaveValue("5");

    await page.getByLabel("Monthly cents").fill("12550");
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect.poll(() => feePatch).toEqual({ default_monthly_cents: 12550 });
  });

  test("session detail adds replacement coach from a selected recurring date", async ({
    page,
  }) => {
    await stubAdminShell(page);
    let replacementPayload: unknown = null;
    let replacementCoachId: string | null = null;

    await page.route("**/api/v2/admin/**", (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && url.pathname === "/api/v2/admin/sessions/series-wed") {
        return fulfillJson(route, {
          session_id: "series-wed",
          coach_id: "coach-scheduled",
          coach_name: "Scheduled Coach",
          title: "Wednesday 6:00 PM - 6:45 PM Beginner",
          location: "Court 1",
          start_at: "2026-06-03T23:00:00Z",
          end_at: "2026-06-03T23:45:00Z",
          days_of_week: ["Wed"],
          start_time: "18:00",
          end_time: "18:45",
          timezone: "America/Chicago",
          capacity: 12,
          status: "scheduled",
          enrolled_count: 0,
          waitlist_count: 0,
        });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-wed/occurrences"
      ) {
        return fulfillJson(route, {
          occurrences: [
            {
              occurrence_id: "series-wed:2026-06-10:18:00",
              session_id: "series-wed",
              start_at: "2026-06-10T23:00:00Z",
              end_at: "2026-06-10T23:45:00Z",
              status: "scheduled",
              scheduled_coach_id: "coach-scheduled",
              actual_coach_id: replacementCoachId,
              substitute_coach_id: null,
              attendance_marked_count: 0,
              attendance_marked_by: [],
              attendance_last_marked_at: null,
              coach_attendance: [],
            },
          ],
        });
      }
      if (
        request.method() === "PATCH" &&
        url.pathname === "/api/v2/admin/sessions/series-wed/replacement"
      ) {
        replacementPayload = request.postDataJSON();
        replacementCoachId = "coach-replacement";
        return fulfillJson(route, {
          occurrence_id: "series-wed:2026-06-10:18:00",
          session_id: "series-wed",
          start_at: "2026-06-10T23:00:00Z",
          end_at: "2026-06-10T23:45:00Z",
          status: "scheduled",
          scheduled_coach_id: "coach-scheduled",
          actual_coach_id: "coach-replacement",
          substitute_coach_id: null,
          attendance_marked_count: 0,
          attendance_marked_by: [],
          attendance_last_marked_at: null,
          coach_attendance: [],
        });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-wed/enrollments"
      ) {
        return fulfillJson(route, { enrollments: [] });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-wed/waitlist"
      ) {
        return fulfillJson(route, { waitlist: [] });
      }
      if (request.method() === "GET" && url.pathname === "/api/v2/admin/users") {
        return fulfillJson(route, {
          users: [
            {
              user_id: "coach-scheduled",
              email: "scheduled@example.com",
              display_name: "Scheduled Coach",
              role: "coach",
              status: "active",
            },
            {
              user_id: "coach-replacement",
              email: "replacement@example.com",
              display_name: "Replacement Coach",
              role: "coach",
              status: "active",
            },
          ],
        });
      }
      return route.fallback();
    });

    await page.goto("/admin/sessions/series-wed");

    await expect(page.getByText("Replacement coaches")).toBeVisible();
    await expect(page.getByText("Occurrences")).toHaveCount(0);
    await expect(page.getByText("No replacement coaches added.")).toBeVisible();

    await page.getByRole("button", { name: "Add replacement" }).click();
    await page.getByLabel("Date").fill("2026-06-10");
    await page.getByLabel("Replacement coach").selectOption("coach-replacement");
    await page.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => replacementPayload).toEqual({
      date: "2026-06-10",
      replacement_coach_id: "coach-replacement",
      reason: null,
    });
    await expect(page.getByText("No replacement coaches added.")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: "Replacement Coach" })).toBeVisible();
  });
});
