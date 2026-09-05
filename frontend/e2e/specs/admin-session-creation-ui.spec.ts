import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-session-ui-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  // Pre-split admin: migration 0165 grants owner to every existing admin.
  roles: ["admin", "owner"],
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
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "BLNO Badminton Academy",
          academy_slug: "academy-e2e",
          roles: ["admin", "owner"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    });
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

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function nextWednesdayDateInput(): string {
  const value = new Date();
  const daysUntilWednesday = ((3 - value.getDay() + 7) % 7) || 7;
  value.setDate(value.getDate() + daysUntilWednesday);
  return formatDateInput(value);
}

test.describe("admin session creation and fee settings UI", () => {
  test.describe.configure({ mode: "serial" });

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
          amount_cents: 8500,
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

    // The coach field renders a placeholder <input> until the admin/users query
    // resolves, then swaps to a <select>. Wait for the option itself so we never
    // call selectOption() against the "Loading coaches..." input.
    await expect(page.getByLabel("Coach").locator("option[value='coach-e2e']")).toBeAttached();
    await page.getByLabel("Coach").selectOption("coach-e2e");
    await page.getByLabel("Name").fill("Intermediate badminton");
    await page.getByLabel("Location").fill("BLNO Court 3");
    await page.getByLabel("Day of week").selectOption("Fri");
    await page.getByLabel("Start time").fill("17:00");
    await page.getByLabel("End time").fill("18:00");
    await page.getByLabel("Capacity").fill("12");
    await page.getByLabel("Monthly fee").fill("85");
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
      amount_cents: 8500,
    });
  });

  test("fee settings focus on late-payment policy instead of session tuition", async ({ page }) => {
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

    await expect(page.getByLabel("Monthly cents")).toHaveCount(0);
    await expect(page.getByLabel("Late fee ($)")).toHaveValue("15.00");
    await expect(page.getByLabel("Grace days")).toHaveValue("5");

    await page.getByLabel("Late fee ($)").fill("17.50");
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect.poll(() => feePatch).toEqual({ late_fee_cents: 1750 });
  });

  test("invoice schedule panel reads and saves billing day and grace days (#651)", async ({
    page,
  }) => {
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/academy/fees", (route) =>
      fulfillJson(route, { default_monthly_cents: 12000, late_fee_cents: 1500, grace_days: 5 }),
    );
    let schedulePut: unknown = null;
    await page.route("**/api/v2/admin/billing/settings/invoice-schedule", (route) => {
      const request = route.request();
      if (request.method() === "GET") {
        return fulfillJson(route, { billing_day: 1, invoice_due_days: 7 });
      }
      if (request.method() === "PUT") {
        schedulePut = request.postDataJSON();
        return fulfillJson(route, { billing_day: 1, invoice_due_days: 10 });
      }
      return route.fallback();
    });

    await page.goto("/admin/settings?panel=fees");

    const panel = page.getByTestId("invoice-schedule-panel");
    await expect(panel).toContainText("9:00 AM academy time");
    await expect(page.getByTestId("invoice-schedule-billing-day")).toHaveValue("1");
    await expect(page.getByTestId("invoice-schedule-due-days")).toHaveValue("7");
    await expect(page.getByTestId("invoice-schedule-save")).toBeDisabled();

    await page.getByTestId("invoice-schedule-due-days").fill("10");
    await page.getByTestId("invoice-schedule-save").click();

    await expect.poll(() => schedulePut).toEqual({ billing_day: 1, invoice_due_days: 10 });
    await expect(panel).toContainText("Saved.");
  });

  test("dashboard recent payments show money received with method", async ({ page }) => {
    await stubAdminShell(page);

    await page.route("**/api/v2/admin/sessions*", (route) =>
      fulfillJson(route, { sessions: [] }),
    );
    await page.route("**/api/v2/admin/payments", (route) =>
      fulfillJson(route, { payments: [] }),
    );
    await page.route("**/api/v2/admin/payments/feed*", (route) =>
      fulfillJson(route, {
        payments: [
          {
            payment_id: "pay_65bd7fae",
            parent_id: "parent-1",
            parent_name: "Abhishek Ajithkumar",
            amount_cents: 6000,
            refunded_cents: 0,
            currency: "usd",
            status: "succeeded",
            payment_method: "stripe_checkout",
            paid_at: "2026-06-03T12:00:00Z",
          },
          {
            payment_id: "pay_zelle_01",
            parent_id: "parent-2",
            parent_name: "Murugesan KP",
            amount_cents: 6000,
            refunded_cents: 0,
            currency: "usd",
            status: "succeeded",
            payment_method: "zelle",
            paid_at: "2026-06-02T12:00:00Z",
          },
        ],
      }),
    );
    await page.route("**/api/v2/admin/finance/revenue", (route) =>
      fulfillJson(route, { by_month: { "2026-06": 6000 } }),
    );
    await page.route("**/api/v2/admin/attention", (route) =>
      fulfillJson(route, { items: [] }),
    );

    await page.goto("/admin");

    const recentPayments = page.getByTestId("admin-dashboard-recent-payments");
    await expect(recentPayments).toContainText("Abhishek Ajithkumar");
    await expect(recentPayments).toContainText("STRIPE");
    await expect(recentPayments).toContainText("Murugesan KP");
    await expect(recentPayments).toContainText("ZELLE");
    await expect(recentPayments).not.toContainText("pay_65bd");
  });

  test("session detail adds replacement coach from a selected recurring date", async ({
    page,
  }) => {
    await stubAdminShell(page);
    let replacementPayload: unknown = null;
    let replacementCoachId: string | null = null;
    const replacementDate = nextWednesdayDateInput();

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
              occurrence_id: `series-wed:${replacementDate}:18:00`,
              session_id: "series-wed",
              start_at: `${replacementDate}T23:00:00Z`,
              end_at: `${replacementDate}T23:45:00Z`,
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
          occurrence_id: `series-wed:${replacementDate}:18:00`,
          session_id: "series-wed",
          start_at: `${replacementDate}T23:00:00Z`,
          end_at: `${replacementDate}T23:45:00Z`,
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

    await expect(page.getByRole("heading", { name: "Replacement coaches" })).toBeVisible();
    await expect(page.getByText("Occurrences")).toHaveCount(0);
    await expect(page.getByText("No replacement coaches added.")).toBeVisible();

    await page.getByRole("button", { name: "Add replacement" }).click();
    await page.getByLabel("Date").fill(replacementDate);
    // Same placeholder-input-then-<select> swap as the create dialog above; this
    // is the race that made this test flaky in CI (WebKit, PR #351).
    await expect(
      page.getByLabel("Replacement coach").locator("option[value='coach-replacement']"),
    ).toBeAttached();
    await page.getByLabel("Replacement coach").selectOption("coach-replacement");
    await page.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => replacementPayload).toEqual({
      date: replacementDate,
      replacement_coach_id: "coach-replacement",
      reason: null,
    });
    await expect(page.getByText("No replacement coaches added.")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: "Replacement Coach" })).toBeVisible();
  });
});
