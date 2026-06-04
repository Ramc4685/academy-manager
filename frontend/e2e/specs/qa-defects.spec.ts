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
        { error: { message: "parent raw-id has no Stripe customer" } },
        409,
      );
    });

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Billing portal" }).click();

    await expect(page.getByTestId("billing-portal-error")).toContainText(
      "available after your first successful autopay setup",
    );
    await expect(page.getByTestId("billing-portal-error")).not.toContainText("raw-id");
    await expect(page).toHaveURL(/\/parent\/payments$/);
  });

  test("parent pause request sends resume date contract", async ({ page }) => {
    await stubParentShell(page);
    await page.route("**/api/v2/parent/payments", (route) =>
      fulfillJson(route, { payments: [] }),
    );
    await page.route("**/api/v2/parent/enrollments", (route) =>
      fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: "enr-qa-1",
            student_id: "student-qa-1",
            student_name: "Nila Rao",
            session_id: "session-qa-1",
            session_title: "Thursday Beginner",
            status: "active",
            payment_mode: "monthly",
            subscription_status: "active",
          },
        ],
      }),
    );
    await page.route("**/api/v2/parent/pause-requests", (route) => {
      if (route.request().method() === "POST") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        return fulfillJson(route, {
          pause_request_id: "pause-qa-1",
          parent_id: "user-parent-qa",
          enrollment_id: body.enrollment_id,
          period: body.period,
          pause_kind: body.pause_kind,
          resume_on: body.resume_on,
          reason: body.reason ?? null,
          status: "pending",
          created_at: "2026-06-03T00:00:00Z",
          decided_at: null,
          decided_by: null,
        });
      }
      return fulfillJson(route, { requests: [] });
    });
    await page.route("**/api/v2/parent/credits", (route) =>
      fulfillJson(route, { balance_cents: 0, credits: [] }),
    );

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Request pause" }).click();
    await page.getByLabel("Requested resume date").fill("2026-07-15");
    await page.getByLabel("Reason").fill("Summer travel");

    const pausePost = page.waitForRequest((request) => {
      return (
        request.method() === "POST" &&
        request.url().includes("/api/v2/parent/pause-requests")
      );
    });
    await page.getByRole("button", { name: "Submit" }).click();

    const payload = JSON.parse((await pausePost).postData() ?? "{}");
    expect(payload).toMatchObject({
      enrollment_id: "enr-qa-1",
      pause_kind: "fixed",
      resume_on: "2026-07-15",
      period: "2026-07",
      reason: "Summer travel",
    });
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
      { timeout: 15000 },
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
      { timeout: 15000 },
    );
  });
});
