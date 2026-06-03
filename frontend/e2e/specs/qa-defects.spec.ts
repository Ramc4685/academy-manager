import { expect, test } from "@playwright/test";

import { ACADEMY_A, fulfillJson, stubMe } from "../fixtures/saas-stubs";

const draftApplication = {
  application_id: "app-qa-1",
  status: "DRAFT",
  parent_profile: {
    first_name: "",
    last_name: "",
    email: "parent@example.com",
    phone: "",
  },
  child_profile: {
    first_name: "",
    last_name: "",
    date_of_birth: "",
    skill_level: "",
  },
  selected_session_id: null,
  waiver_accepted: false,
  expires_at: "2026-05-27T00:00:00Z",
};

async function stubParentShell(page: Parameters<typeof stubMe>[0]) {
  await stubMe(page, {
    user_id: "user-parent-qa",
    email: "parent@example.com",
    academy_id: ACADEMY_A,
    roles: ["parent"],
  });
}

async function stubParentPayments(page: Parameters<typeof stubMe>[0]) {
  await page.route("**/api/v2/parent/payments", (route) =>
    fulfillJson(route, { payments: [] }),
  );
  await page.route("**/api/v2/parent/enrollments", (route) =>
    fulfillJson(route, { enrollments: [] }),
  );
  await page.route("**/api/v2/parent/pause-requests", (route) =>
    fulfillJson(route, { requests: [] }),
  );
  await page.route("**/api/v2/parent/credits", (route) =>
    fulfillJson(route, { balance_cents: 0, credits: [] }),
  );
}

test.describe("QA defect regressions", () => {
  test("parent onboarding child step uses stable date and skill controls", async ({
    page,
  }) => {
    await stubParentShell(page);
    await page.route("**/api/v2/parent/onboarding/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, draftApplication);
    });
    await page.route("**/api/v2/parent/onboarding/app-qa-1", async (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      const patch = JSON.parse(route.request().postData() ?? "{}");
      return fulfillJson(route, {
        ...draftApplication,
        parent_profile: {
          ...draftApplication.parent_profile,
          ...(patch.parent_profile ?? {}),
        },
        child_profile: {
          ...draftApplication.child_profile,
          ...(patch.child_profile ?? {}),
        },
      });
    });
    await page.route("**/api/v2/parent/sessions/available", (route) =>
      fulfillJson(route, { sessions: [] }),
    );

    await page.goto("/parent/onboarding");
    await page.getByLabel("First name").fill("Rina");
    await page.getByLabel("Last name").fill("Patel");
    await page.getByLabel("Phone").fill("555-0100");
    await page
      .getByTestId("parent-onboarding")
      .getByRole("button", { name: "Next" })
      .click();

    const dob = page.getByLabel("Date of birth");
    await expect(dob).toHaveAttribute("type", "text");
    await dob.fill("2014-02-03");
    await expect(dob).toHaveValue("2014-02-03");
    await page.getByRole("radio", { name: "Beginner" }).click();
    await expect(page.getByRole("radio", { name: "Beginner" })).toBeChecked();
  });

  test("billing portal failures are visible to parents", async ({ page }) => {
    await stubParentShell(page);
    await stubParentPayments(page);
    await page.route("**/api/v2/parent/billing/portal", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(
        route,
        { detail: "Stripe billing portal is unavailable" },
        503,
      );
    });

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Billing portal" }).click();

    await expect(page.getByTestId("billing-portal-error")).toContainText(
      "Billing portal",
    );
    await expect(page).toHaveURL(/\/parent\/payments$/);
  });

  test("wrong-role admin redirects explain the access denial", async ({
    page,
  }) => {
    await stubParentShell(page);
    await stubParentPayments(page);

    await page.goto("/admin");

    await expect(page).toHaveURL(/\/parent\/payments\?access_denied=admin/);
    await expect(page.getByTestId("persona-access-denied")).toContainText(
      "admin access",
    );
  });

  test("wrong-role coach redirects explain the access denial", async ({
    page,
  }) => {
    await stubParentShell(page);
    await stubParentPayments(page);

    await page.goto("/coach/sessions");

    await expect(page).toHaveURL(/\/parent\/payments\?access_denied=coach/, {
      timeout: 15000,
    });
    await expect(page.getByTestId("persona-access-denied")).toContainText(
      "coach access",
    );
  });
});
