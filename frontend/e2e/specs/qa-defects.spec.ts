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
  await page.route("**/api/v2/parent/invoices", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { invoices: [] });
  });
}

async function stubParentPayments(page: Parameters<typeof stubMe>[0]) {
  await page.route("**/api/v2/parent/payments", (route) =>
    fulfillJson(route, { payments: [] }),
  );
  await page.route("**/api/v2/parent/invoices", (route) =>
    fulfillJson(route, { invoices: [] }),
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
  test("child registration confirmation does not claim payment was received", async ({
    page,
  }) => {
    await stubParentShell(page);
    await page.route(
      "**/api/v2/parent/onboarding/app-qa-child/status",
      (route) =>
        fulfillJson(route, {
          ...draftApplication,
          application_id: "app-qa-child",
          status: "PENDING_APPROVAL",
          child_profile: {
            ...draftApplication.child_profile,
            first_name: "Kavan",
            last_name: "Chandran",
          },
        }),
    );

    await page.goto("/parent/checkout/return?application_id=app-qa-child");

    await expect(page.getByRole("heading", { name: "Child added" })).toBeVisible();
    await expect(page.getByTestId("status-text")).toHaveText(
      "Kavan has been added. An admin will confirm the enrollment shortly.",
    );
    await expect(page.getByText("Payment received", { exact: true })).toHaveCount(0);
  });

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

  test("parent onboarding shows waiver text and advances to session after accept", async ({
    page,
  }) => {
    await stubParentShell(page);
    let acceptedWaiver = false;
    let currentApplication = { ...draftApplication };

    await page.route("**/api/v2/parent/onboarding/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, currentApplication);
    });
    await page.route("**/api/v2/parent/onboarding/waiver", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        configured: true,
        version: "1.0",
        body: "BLNO Liability Waiver\nParent agrees to academy safety rules.",
      });
    });
    await page.route("**/api/v2/parent/onboarding/app-qa-1", async (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      const patch = JSON.parse(route.request().postData() ?? "{}");
      if (patch.accept_waiver === true) acceptedWaiver = true;
      currentApplication = {
        ...currentApplication,
        parent_profile: {
          ...currentApplication.parent_profile,
          ...(patch.parent_profile ?? {}),
        },
        child_profile: {
          ...currentApplication.child_profile,
          ...(patch.child_profile ?? {}),
        },
        waiver_accepted: currentApplication.waiver_accepted || patch.accept_waiver === true,
      };
      return fulfillJson(route, currentApplication);
    });
    await page.route("**/api/v2/parent/sessions/available", (route) =>
      fulfillJson(route, {
        sessions: [
          {
            session_id: "session-qa-1",
            title: "Thursday Beginner",
            location: "Court 1",
            start_at: "2026-06-25T23:00:00Z",
            end_at: "2026-06-26T00:00:00Z",
            capacity: 8,
            enrolled_count: 3,
            available_seats: 5,
            amount_cents: 7000,
          },
        ],
      }),
    );

    await page.goto("/parent/onboarding");
    const parentForm = page.locator("form").filter({ hasText: "Your details" });
    await expect(parentForm.getByRole("heading", { name: "Your details" })).toBeVisible();
    await parentForm.getByLabel("First name").fill("Rina");
    await parentForm.getByLabel("Last name").fill("Patel");
    await parentForm.getByRole("button", { name: "Next" }).click();

    const childForm = page.locator("form").filter({ hasText: "Your child" });
    await expect(childForm.getByRole("heading", { name: "Your child" })).toBeVisible();
    await childForm.getByLabel("First name").fill("Ava");
    await childForm.getByLabel("Last name").fill("Patel");
    await childForm.getByLabel("Date of birth").fill("2014-02-03");
    await expect(childForm.getByLabel("First name")).toHaveValue("Ava");
    await childForm.getByRole("radio", { name: "Beginner" }).click();
    await childForm.getByRole("button", { name: "Next" }).click();

    await expect(page.getByText("BLNO Liability Waiver")).toBeVisible();
    await expect(page.getByText("Parent agrees to academy safety rules.")).toBeVisible();
    await page.getByRole("button", { name: "I Accept" }).click();

    await expect(page.getByRole("heading", { name: "Pick a session" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Thursday Beginner/ })).toBeVisible();
    expect(acceptedWaiver).toBe(true);
  });

  test("billing portal failures are visible to parents", async ({ page }) => {
    await stubParentShell(page);
    await stubParentPayments(page);
    await page.route("**/api/v2/parent/billing/portal", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(
        route,
        { detail: "Billing portal will be available after the first successful autopay setup." },
        409,
      );
    });

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Billing portal" }).click();

    await expect(page.getByTestId("billing-portal-error")).toContainText(
      "Start autopay for an enrollment first",
    );
    await expect(page.getByTestId("billing-portal-error")).not.toContainText("Request failed");
    await expect(page).toHaveURL(/\/parent\/payments$/);
  });

  test("autopay checkout failures are visible to parents", async ({ page }) => {
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
            payment_mode: null,
            subscription_status: null,
            autopay_enrollment_status: null,
          },
        ],
      }),
    );
    await page.route("**/api/v2/parent/pause-requests", (route) =>
      fulfillJson(route, { requests: [] }),
    );
    await page.route("**/api/v2/parent/credits", (route) =>
      fulfillJson(route, { balance_cents: 0, credits: [] }),
    );
    await page.route("**/api/v2/parent/autopay/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, { detail: "checkout session could not be created" }, 502);
    });

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Set up autopay" }).click();

    await expect(page.getByTestId("autopay-error")).toContainText(
      "Something went wrong starting autopay",
    );
    await expect(page.getByTestId("autopay-error")).not.toContainText("Request failed");
    await expect(page).toHaveURL(/\/parent\/payments$/);
  });

  test("incomplete autopay setup can be retried", async ({ page }) => {
    // Regression: an abandoned Stripe Checkout used to leave the enrollment at
    // autopay_enrollment_status="setup_started", which rendered a disabled
    // "Autopay on" button and locked parents out of autopay forever.
    await stubParentShell(page);
    await page.route("**/api/v2/parent/payments", (route) =>
      fulfillJson(route, { payments: [] }),
    );
    await page.route("**/api/v2/parent/enrollments", (route) =>
      fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: "enr-qa-2",
            student_id: "student-qa-1",
            student_name: "Nila Rao",
            session_id: "session-qa-1",
            session_title: "Thursday Beginner",
            status: "active",
            payment_mode: "monthly",
            subscription_status: "incomplete",
            autopay_enrollment_status: "setup_started",
          },
        ],
      }),
    );
    await page.route("**/api/v2/parent/pause-requests", (route) =>
      fulfillJson(route, { requests: [] }),
    );
    await page.route("**/api/v2/parent/credits", (route) =>
      fulfillJson(route, { balance_cents: 0, credits: [] }),
    );

    await page.goto("/parent/payments");

    await expect(page.getByText("Payment setup pending")).toBeVisible();
    const retryButton = page.getByRole("button", { name: "Retry autopay" });
    await expect(retryButton).toBeVisible();
    await expect(retryButton).toBeEnabled();
  });

  test("autopay success return reconciles checkout before showing active state", async ({
    page,
  }) => {
    await stubParentShell(page);
    let enrollmentReads = 0;
    await page.route("**/api/v2/parent/payments", (route) =>
      fulfillJson(route, { payments: [] }),
    );
    await page.route("**/api/v2/parent/enrollments", (route) => {
      enrollmentReads += 1;
      return fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: "enr-qa-3",
            student_id: "student-qa-1",
            student_name: "Nila Rao",
            session_id: "session-qa-1",
            session_title: "Thursday Beginner",
            status: "active",
            payment_mode: "monthly",
            subscription_status: enrollmentReads > 1 ? "active" : "incomplete",
            autopay_enrollment_status: enrollmentReads > 1 ? "active" : "setup_started",
          },
        ],
      });
    });
    await page.route("**/api/v2/parent/checkout/status/cs_return_123", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      return fulfillJson(route, {
        checkout_session_id: "cs_return_123",
        payment_id: null,
        status: "active",
        parent_id: "user-parent-qa",
      });
    });
    await page.route("**/api/v2/parent/pause-requests", (route) =>
      fulfillJson(route, { requests: [] }),
    );
    await page.route("**/api/v2/parent/credits", (route) =>
      fulfillJson(route, { balance_cents: 0, credits: [] }),
    );

    await page.goto("/parent/payments?autopay=success&checkout_session_id=cs_return_123");

    await expect(page.getByTestId("autopay-checkout-confirming")).toBeVisible();
    await expect(page.getByText("Autopay active")).toBeVisible();
    await expect(page.getByRole("button", { name: "Autopay on" })).toBeDisabled();
    expect(enrollmentReads).toBeGreaterThan(1);
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
            autopay_enrollment_status: "active",
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
    await page.getByRole("button", { name: "Pause enrollment", exact: true }).click();
    await page.getByLabel("Resume date").fill("2026-07-15");
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

    const meResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/v2/me") && response.status() === 200,
    );
    await page.goto("/admin", { waitUntil: "domcontentloaded" });
    await meResponse;

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

    const meResponse = page.waitForResponse((response) =>
      response.url().endsWith("/api/v2/me") && response.status() === 200,
    );
    await page.goto("/coach/sessions", { waitUntil: "domcontentloaded" });
    await meResponse;

    await expect(page).toHaveURL(/\/parent\/payments\?access_denied=coach/, {
      timeout: 15000,
    });
    await expect(page.getByTestId("persona-access-denied")).toContainText(
      "coach access",
      { timeout: 15000 },
    );
  });
});
