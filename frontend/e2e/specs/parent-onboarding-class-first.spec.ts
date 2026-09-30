/**
 * Class-first onboarding order (Settings overhaul Phase 6, waiver follow-up).
 *
 * The right set of waivers is only known once the family has picked a class
 * when a waiver is assigned to a program, so the stepper asks for the class
 * BEFORE the waiver:
 *
 *   program-scoped waiver:    parent, child, class, waiver, review
 *   only an all-family waiver: parent, child, waiver, class, review (as before)
 *
 * The class step is the stepper's `session` step. The server tells the page
 * which order to use through `waiver_class_first` on the application. Mocks
 * the v2 BFF at the Playwright route layer, like the other parent specs, so
 * no unstubbed route can 404 into the assertions.
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

const APPLICATION_ID = "app-class-first-1";
const SESSION_ID = "sess-juniors-1";
const STUDENT_ID = "st-class-first-1";

const EXISTING_CHILD = {
  student_id: STUDENT_ID,
  full_name: "Ava Kim",
  date_of_birth: "2015-04-02",
  emergency_contact_name: "Jo Kim",
  emergency_contact_phone: "+1 555 0100",
  medical_notes: "Peanut allergy",
  no_medical_conditions: false,
};

function draftApplication(classFirst: boolean) {
  return {
    application_id: APPLICATION_ID,
    status: "DRAFT",
    parent_profile: {
      first_name: "Jo",
      last_name: "Kim",
      email: "parent@example.com",
      phone: "+1 555 0100",
    },
    child_profile: {
      first_name: "",
      last_name: "",
      date_of_birth: "",
      skill_level: "",
      emergency_contact_name: "",
      emergency_contact_phone: "",
      medical_notes: "",
    },
    selected_session_id: null,
    waiver_accepted: false,
    waiver_class_first: classFirst,
    expires_at: "2027-05-27T00:00:00Z",
  };
}

const SESSION = {
  session_id: SESSION_ID,
  title: "Juniors Saturday",
  location: "Court 1",
  start_at: "2027-06-05T15:00:00Z",
  end_at: "2027-06-05T16:00:00Z",
  timezone: "UTC",
  capacity: 12,
  enrolled_count: 3,
  available_seats: 9,
  amount_cents: 12000,
};

async function stubOnboarding(
  page: Page,
  classFirst: boolean,
): Promise<{ waiverRequests: string[] }> {
  const waiverRequests: string[] = [];
  const application = draftApplication(classFirst);
  await stubMe(page, {
    user_id: "user-parent-class-first",
    email: "parent@example.com",
    academy_id: ACADEMY_A,
    roles: ["parent"],
  });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Academy A", role: "parent" },
  ]);
  await stubParentProfile(page, {
    user_id: "user-parent-class-first",
    children: [EXISTING_CHILD],
  });
  await stubParentMessages(page);
  await stubParentAcademy(page);
  await page.route("**/api/v2/parent/invoices", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { invoices: [] });
  });
  await page.route("**/api/v2/parent/sessions/available", (route) =>
    fulfillJson(route, { sessions: [SESSION] }),
  );
  await page.route("**/api/v2/parent/enrollments/quote", (route) =>
    fulfillJson(route, {
      snapshot_id: "snap-1",
      amount_due_cents: 12000,
      monthly_price_cents: 12000,
      billing_period: "2027-06",
      total_eligible_classes_this_month: 4,
      billable_remaining_classes_this_month: 4,
      formula: "flat",
      message: "Monthly price",
      next_billing_amount_cents: 12000,
      next_billing_message: "Next month",
    }),
  );
  await page.route("**/api/v2/parent/onboarding/start", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return fulfillJson(route, application);
  });
  let saved = application;
  await page.route(`**/api/v2/parent/onboarding/${APPLICATION_ID}`, (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    const patch = JSON.parse(route.request().postData() ?? "{}");
    saved = {
      ...saved,
      parent_profile: { ...saved.parent_profile, ...(patch.parent_profile ?? {}) },
      child_profile: { ...saved.child_profile, ...(patch.child_profile ?? {}) },
      selected_session_id: patch.selected_session_id ?? saved.selected_session_id,
      waiver_accepted: patch.accept_waiver ?? saved.waiver_accepted,
    };
    return fulfillJson(route, saved);
  });
  await page.route("**/api/v2/parent/onboarding/waiver**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    waiverRequests.push(route.request().url());
    const liability = {
      waiver_template_id: "wt-liability",
      title: "Liability waiver",
      version: "3",
      body: "Liability text",
    };
    const photo = {
      waiver_template_id: "wt-photo",
      title: "Photo consent",
      version: "1",
      body: "Photo consent text",
    };
    return fulfillJson(route, {
      configured: true,
      version: liability.version,
      body: liability.body,
      class_first: classFirst,
      waivers: classFirst ? [liability, photo] : [liability],
    });
  });
  return { waiverRequests };
}

/** The stepper's labels, left to right. */
function stepLabels(page: Page) {
  return page.getByTestId("onboarding-progress").locator("li button span:last-child");
}

/** Parent step, then the child step (the returning child is pre-filled). */
async function throughParentAndChild(page: Page) {
  const next = page.getByTestId("parent-onboarding").getByRole("button", { name: "Next" });
  await page.goto(`/parent/onboarding?child=${STUDENT_ID}`);
  await expect(page.getByRole("heading", { name: "Your details" })).toBeVisible();
  await next.click();
  await expect(page.getByRole("heading", { name: "Your child" })).toBeVisible();
  await page.getByRole("radio", { name: "beginner" }).click();
  await next.click();
}

test.describe("class-first onboarding order", () => {
  test("a program-scoped waiver asks for the class before the waiver", async ({ page }) => {
    const { waiverRequests } = await stubOnboarding(page, true);

    await throughParentAndChild(page);

    await expect(stepLabels(page)).toHaveText(["parent", "child", "session", "waiver", "review"]);
    // Third step is the class; no waiver is fetched before one is chosen.
    await expect(page.getByRole("heading", { name: "Pick a session" })).toBeVisible();
    expect(waiverRequests).toHaveLength(0);

    await page.getByRole("button", { name: /Juniors Saturday/ }).click();

    // The waivers shown are the chosen class's, fetched with that class.
    await expect(page.getByRole("heading", { name: "Waivers" })).toBeVisible();
    await expect(page.getByTestId("onboarding-waivers")).toContainText("Photo consent");
    await expect.poll(() => waiverRequests.at(-1) ?? "").toContain(`session_id=${SESSION_ID}`);
  });

  test("only an all-family waiver keeps today's order: waiver, then class", async ({ page }) => {
    const { waiverRequests } = await stubOnboarding(page, false);

    await throughParentAndChild(page);

    await expect(stepLabels(page)).toHaveText(["parent", "child", "waiver", "session", "review"]);
    await expect(page.getByRole("heading", { name: "Waiver", exact: true })).toBeVisible();
    // Asked without a class, exactly as it always was. The step heading can
    // render before the waiver request goes out, so wait for the request.
    await expect.poll(() => waiverRequests.length).toBeGreaterThan(0);
    await expect(page.getByTestId("onboarding-waivers").or(page.getByText("Liability text"))).toBeVisible();
    expect(waiverRequests.every((url) => !url.includes("session_id"))).toBe(true);

    await page.getByRole("button", { name: "I Accept" }).click();
    await expect(page.getByRole("heading", { name: "Pick a session" })).toBeVisible();
  });
});
