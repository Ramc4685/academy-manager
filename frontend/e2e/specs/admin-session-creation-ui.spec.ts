import { expect, test, type Page, type Route } from "@playwright/test";

import { billingRulesFixture } from "../fixtures/billing-rules";

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

// Class-page PR A: the price is a plan picker fed by the owner-only Pricing
// overview, and Create has an optional welcome-email step whose absence
// placeholder comes from the family policies.
const PRICING_OVERVIEW = {
  plans: [
    {
      plan_id: "plan-group",
      name: "Group class",
      description: null,
      price_cents: 6000,
      plan_type: "monthly",
      is_active: true,
      linked_classes: 0,
      updated_at: "2026-09-01T00:00:00Z",
    },
  ],
  classes: [],
  saved_overrides: [],
  auto_linkable: 0,
};

async function stubClassFormReads(page: Page) {
  await page.route("**/api/v2/admin/pricing", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, PRICING_OVERVIEW);
  });
  await page.route("**/api/v2/admin/self-service/policy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      welcome_email_absence_policy_default: "Tell us 24 hours ahead for a make-up.",
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

test.describe("admin session creation and billing-rules settings UI", () => {
  test.describe.configure({ mode: "serial" });

  test("create session dialog opens, fills form, and preserves the API payload", async ({
    page,
  }) => {
    await stubAdminShell(page);
    await stubClassFormReads(page);
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
    await page.getByRole("button", { name: "Create", exact: true }).click();

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

  test("create session with a pricing plan links the class and sends only typed welcome-email fields", async ({
    page,
  }) => {
    await stubAdminShell(page);
    await stubClassFormReads(page);
    let createPayload: Record<string, unknown> | null = null;
    let linkPayload: unknown = null;

    await page.route("**/api/v2/admin/sessions*", (route) => {
      const request = route.request();
      if (request.method() === "GET") return fulfillJson(route, { sessions: [] });
      if (request.method() === "POST") {
        createPayload = request.postDataJSON() as Record<string, unknown>;
        return fulfillJson(route, {
          session_id: "session-plan-e2e",
          coach_id: "coach-e2e",
          title: "Group badminton",
          location: "BLNO Court 1",
          start_at: "2026-05-29T17:00:00Z",
          end_at: "2026-05-29T18:00:00Z",
          days_of_week: ["Fri"],
          start_time: "17:00",
          end_time: "18:00",
          timezone: "America/Chicago",
          capacity: 12,
          amount_cents: 6000,
          status: "scheduled",
          enrolled_count: 0,
          waitlist_count: 0,
        });
      }
      return route.fallback();
    });
    await page.route("**/api/v2/admin/pricing/classes/*/plan", (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      linkPayload = route.request().postDataJSON();
      return fulfillJson(route, {
        session_id: "session-plan-e2e",
        title: "Group badminton",
        charged_cents: 6000,
        fee_set: true,
        students: 0,
        plan_id: "plan-group",
        matching_plan_ids: ["plan-group"],
        stale_link: false,
      });
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
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Create session" })).toBeVisible();

    await expect(dialog.getByLabel("Coach").locator("option[value='coach-e2e']")).toBeAttached();
    await dialog.getByLabel("Coach").selectOption("coach-e2e");
    await dialog.getByLabel("Name").fill("Group badminton");
    await dialog.getByLabel("Location").fill("BLNO Court 1");
    await dialog.getByLabel("Day of week").selectOption("Fri");
    await dialog.getByLabel("Start time").fill("17:00");
    await dialog.getByLabel("End time").fill("18:00");
    await dialog.getByLabel("Capacity").fill("12");
    await expect(dialog.getByTestId("class-form-price").locator("option[value='plan-group']")).toBeAttached();
    await dialog.getByTestId("class-form-price").selectOption("plan-group");
    // A plan sets the fee, so there is no fee box to type in.
    await expect(dialog.getByTestId("create-session-monthly-fee")).toHaveCount(0);

    await dialog.getByRole("button", { name: "Welcome email (optional)" }).click();
    // The academy's absence default shows as a placeholder, not a value.
    const absence = dialog.getByLabel("Absence & make-up policy");
    await expect(absence).toHaveAttribute(
      "placeholder",
      "Uses academy default: Tell us 24 hours ahead for a make-up.",
    );
    await expect(absence).toHaveValue("");
    await dialog.getByLabel("WhatsApp group link").fill("https://chat.whatsapp.com/AbCd1234");
    await dialog.getByRole("button", { name: "Create" }).click();

    await expect.poll(() => createPayload).not.toBeNull();
    expect(createPayload).toMatchObject({
      amount_cents: 6000,
      whatsapp_group_link: "https://chat.whatsapp.com/AbCd1234",
    });
    // Blank welcome-email boxes are left out so the class uses the academy default.
    for (const key of [
      "venue_address",
      "parking_notes",
      "what_to_bring",
      "arrival_minutes_before",
      "coach_contact_policy",
      "absence_policy",
    ]) {
      expect(createPayload).not.toHaveProperty(key);
    }
    await expect.poll(() => linkPayload).toEqual({ plan_id: "plan-group" });
  });

  // #917: the old sidebar entry pointed at /admin/waitlist, which has never
  // been a page. The queue lives on the Inbox, so the sessions page carries a
  // link straight to that tab.
  test("sessions page links to the waitlist queue on the inbox", async ({ page }) => {
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/sessions*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { sessions: [] });
    });
    await page.route("**/api/v2/admin/inbox/counts*", (route) =>
      fulfillJson(route, { counts: {}, total: 0 }),
    );

    await page.goto("/admin/sessions");
    const link = page.getByTestId("admin-sessions-waitlist-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/admin/inbox?tab=waitlist");
    // Create session stays on the same row, not displaced by the new link.
    await expect(page.getByTestId("admin-sessions-create")).toBeVisible();
  });

  test("billing rules save the late fee and the invoice schedule from one panel", async ({
    page,
  }) => {
    await stubAdminShell(page);
    let rulesPut: unknown = null;

    await page.route("**/api/v2/admin/billing/rules", (route) => {
      const request = route.request();
      if (request.method() === "GET") return fulfillJson(route, billingRulesFixture());
      if (request.method() === "PUT") {
        rulesPut = request.postDataJSON();
        return fulfillJson(
          route,
          billingRulesFixture(request.postDataJSON() as Record<string, number>),
        );
      }
      return route.fallback();
    });

    await page.goto("/admin/settings?panel=billing-rules");

    // The dead per-session tuition field is gone for good.
    await expect(page.getByLabel("Monthly cents")).toHaveCount(0);
    await expect(page.getByTestId("billing-rules-input-late_fee_cents")).toHaveValue("15.00");
    await expect(page.getByTestId("billing-rules-input-grace_days")).toHaveValue("5");
    await expect(page.getByTestId("billing-rules-input-billing_day")).toHaveValue("1");
    await expect(page.getByTestId("billing-rules-input-invoice_due_days")).toHaveValue("7");
    await expect(page.getByTestId("billing-rules-save")).toBeDisabled();

    await page.getByTestId("billing-rules-input-late_fee_cents").fill("17.50");
    await page.getByTestId("billing-rules-input-invoice_due_days").fill("10");
    await page.getByTestId("billing-rules-save").click();

    await expect.poll(() => rulesPut).toEqual({ invoice_due_days: 10, late_fee_cents: 1750 });
    await expect(page.getByTestId("billing-rules-saved")).toBeVisible();
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

    // #671 merged "Replacement coaches" into the single "Class dates" card.
    await page.getByRole("button", { name: "Class dates", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Class dates" })).toBeVisible();
    await expect(page.getByText("Occurrences")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: "Replacement Coach" })).toHaveCount(0);

    await page.getByRole("button", { name: "Add replacement" }).click();
    // Exact: `getByLabel` matches a case-insensitive SUBSTRING, so a loose
    // "Date" also matches the phone list's `aria-label="Class dates"` (#857).
    await page.getByLabel("Date", { exact: true }).fill(replacementDate);
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
    // Issue #671 folded the replacement-coach table into the single "Class
    // dates" card, so a replaced date is listed exactly ONCE. Counted by row
    // rather than by table cell: below `md` the card renders phone rows and
    // has no cells at all (#857).
    await expect(
      page
        .locator('[data-testid^="class-date-row-"]')
        .filter({ hasText: "Replacement Coach" }),
    ).toHaveCount(1);
  });
});
