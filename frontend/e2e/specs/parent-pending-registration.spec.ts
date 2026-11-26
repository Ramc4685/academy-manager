/**
 * S02: a second registration for the same child and class is refused in plain
 * words, and the first one stays listed on Home as waiting for the academy.
 *
 * Mocks the v2 BFF at the Playwright route layer, like the other parent specs.
 */

import { expect, test, type Page } from "@playwright/test";

import {
  ACADEMY_A,
  fulfillJson,
  stubMe,
  stubMemberships,
  stubParentAcademy,
  stubParentMessages,
  stubParentProfile,
} from "../fixtures/saas-stubs";

const REFUSAL =
  "Lucia is already registered for this class. You can see it on your Home page; we will email you when the academy confirms.";

const SESSION = {
  session_id: "sess-free",
  title: "Free Clinic",
  location: "Court 1",
  start_at: "2027-06-05T15:00:00Z",
  end_at: "2027-06-05T16:00:00Z",
  timezone: "UTC",
  capacity: 12,
  enrolled_count: 3,
  available_seats: 9,
  amount_cents: 0,
};

/** A second try for Lucia, filled in and ready to pay. */
const SECOND_TRY = {
  application_id: "app-lucia-again",
  status: "DRAFT",
  parent_profile: {
    first_name: "Ana",
    last_name: "Rivera",
    email: "new.parent@example.com",
    phone: "555-0142",
  },
  child_profile: {
    first_name: "Lucia",
    last_name: "Rivera",
    date_of_birth: "2016-03-04",
    skill_level: "beginner",
    emergency_contact_name: "Ana Rivera",
    emergency_contact_phone: "555-0142",
    medical_notes: "",
  },
  selected_session_id: SESSION.session_id,
  waiver_accepted: true,
  waiver_class_first: false,
  expires_at: "2027-05-27T00:00:00Z",
};

const WAITING_ROW = {
  application_id: "app-lucia",
  child_first_name: "Lucia",
  session_id: SESSION.session_id,
  session_title: SESSION.title,
  schedule_label: "Saturdays 10:00 AM",
  status: "PENDING_APPROVAL",
  state: "waiting",
  submitted_at: "2026-11-25T15:00:00Z",
};

async function stubShell(page: Page): Promise<void> {
  await stubMe(page, {
    user_id: "user-parent-s02",
    email: "new.parent@example.com",
    academy_id: ACADEMY_A,
    roles: ["parent"],
  });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Academy A", role: "parent" },
  ]);
  await stubParentProfile(page, { user_id: "user-parent-s02" });
  await stubParentMessages(page);
  await stubParentAcademy(page);
  await page.route("**/api/v2/parent/invoices", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { invoices: [] });
  });
  for (const [path, body] of [
    ["children", { children: [] }],
    ["attendance", { records: [] }],
    ["enrollments", { enrollments: [] }],
  ] as const) {
    await page.route(`**/api/v2/parent/${path}`, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, body);
    });
  }
  await page.route("**/api/v2/parent/registrations", (route) =>
    fulfillJson(route, { registrations: [WAITING_ROW] }),
  );
}

test.describe("S02 pending registration", () => {
  test("a second try for the same child and class is refused in plain words", async ({ page }) => {
    await stubShell(page);
    await page.route("**/api/v2/parent/sessions/available", (route) =>
      fulfillJson(route, { sessions: [SESSION] }),
    );
    await page.route("**/api/v2/parent/enrollments/quote", (route) =>
      fulfillJson(route, {
        snapshot_id: "snap-free",
        amount_due_cents: 0,
        monthly_price_cents: 0,
        billing_period: "2027-06",
        total_eligible_classes_this_month: 4,
        billable_remaining_classes_this_month: 4,
        formula: "flat",
        message: "Free",
        next_billing_amount_cents: 0,
        next_billing_message: "Free",
      }),
    );
    await page.route("**/api/v2/parent/onboarding/waiver**", (route) =>
      fulfillJson(route, {
        configured: true,
        consent_text: "I agree to sign electronically.",
        version: "1",
        body: "Liability text",
        class_first: false,
        waivers: [],
      }),
    );
    await page.route("**/api/v2/parent/onboarding/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, SECOND_TRY);
    });
    await page.route("**/api/v2/parent/checkout/start", (route) =>
      fulfillJson(
        route,
        { error: { code: "Onboarding.ApplicationNotEditable", message: REFUSAL } },
        409,
      ),
    );

    await page.goto(`/parent/onboarding?application=${SECOND_TRY.application_id}`);
    const pay = page.getByTestId("checkout-button");
    await expect(pay).toBeEnabled();
    await pay.click();

    const alert = page.getByTestId("parent-onboarding").getByRole("alert");
    await expect(alert).toContainText(REFUSAL);
    await expect(alert).not.toContainText("couldn't start the payment");

    // The first registration is still there, waiting for the academy.
    await page.goto("/parent/children");
    const row = page.getByTestId(`parent-registration-${WAITING_ROW.application_id}`);
    await expect(row).toContainText("Lucia");
    await expect(row).toContainText("Waiting for the academy to confirm");
  });
});
