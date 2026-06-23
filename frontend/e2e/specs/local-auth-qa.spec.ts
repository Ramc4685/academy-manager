import { expect, test, type Page } from "@playwright/test";

const LOCAL_AUTH_ENABLED = process.env.LOCAL_AUTH_E2E === "1";

const PARENT_EMAIL = process.env.LOCAL_AUTH_PARENT_EMAIL ?? "";
const PARENT_PASSWORD = process.env.LOCAL_AUTH_PARENT_PASSWORD ?? "";
const ADMIN_EMAIL = process.env.LOCAL_AUTH_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.LOCAL_AUTH_ADMIN_PASSWORD ?? "";
const COACH_EMAIL = process.env.LOCAL_AUTH_COACH_EMAIL ?? "";
const COACH_PASSWORD = process.env.LOCAL_AUTH_COACH_PASSWORD ?? "";

test.describe("local authenticated QA defect coverage", () => {
  test.skip(
    !LOCAL_AUTH_ENABLED,
    "Set LOCAL_AUTH_E2E=1 and run against scripts/local_test_stack.sh seeded local services."
  );

  test("seeded parent exercises onboarding controls, billing portal redirect, and wrong-role redirects", async ({
    page,
  }) => {
    await signIn(page, PARENT_EMAIL, PARENT_PASSWORD, /\/parent\/payments/);

    await page.goto("/parent/onboarding");
    await expect(page.getByTestId("parent-onboarding")).toBeVisible();
    await page.getByLabel("First name").fill("QA");
    await page.getByLabel("Last name").fill("Parent");
    await page.getByLabel("Phone").fill("555-0199");
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

    await page.goto("/parent/payments");
    await page.getByRole("button", { name: "Billing portal" }).click();
    await expect(page.getByTestId("billing-portal-error")).toContainText(
      "Start autopay for an enrollment first",
    );
    await expect(page.getByTestId("billing-portal-error")).not.toContainText("Request failed");

    await page.goto("/admin");
    await expect(page).toHaveURL(/\/parent\/payments\?access_denied=admin/);
    await expect(page.getByTestId("persona-access-denied")).toContainText("admin access");

    await page.goto("/coach/sessions");
    await expect(page).toHaveURL(/\/parent\/payments\?access_denied=coach/);
    await expect(page.getByTestId("persona-access-denied")).toContainText("coach access");
  });

  test("seeded admin can load the protected admin workspace", async ({ page }) => {
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);

    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
  });

  test("seeded coach can load the protected coach workspace", async ({ page }) => {
    await signIn(page, COACH_EMAIL, COACH_PASSWORD, /\/coach\/today/);

    await page.goto("/coach/sessions");
    await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  });

  test("seeded coach can open an upcoming session from schedule", async ({ page }) => {
    test.slow();
    await signIn(page, COACH_EMAIL, COACH_PASSWORD, /\/coach\/today/);

    await page.goto("/coach/sessions");
    const firstSession = page.locator('a[href*="/coach/sessions/"]').first();
    await expect(firstSession).toContainText("6:00 PM");
    await expect(firstSession).not.toContainText("11:00 PM");
    await firstSession.click();

    await expect(page.getByTestId("session-detail")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Session not found.")).toHaveCount(0);
  });

  test("seeded coach blocker routes render content instead of stale loading states", async ({
    page,
  }) => {
    test.slow();
    await signIn(page, COACH_EMAIL, COACH_PASSWORD, /\/coach\/today/);
    await page.goto("/coach/dashboard");
    await expect(page.getByTestId("coach-dashboard")).toBeVisible();
    await expect(page.getByText("Coach dashboard")).toBeVisible();
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  });

  test("seeded admin blocker routes render content instead of stale loading states", async ({
    page,
  }) => {
    test.slow();
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);
    await page.goto("/admin/pause-requests");
    await expect(page.getByTestId("admin-pause-requests")).toBeVisible();
    await page.goto("/admin/users");
    await expect(page.getByTestId("admin-users")).toBeVisible();
    await page.goto("/messages");
    await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  });

  test("seeded parent blocker routes render content instead of stale loading states", async ({
    page,
  }) => {
    test.slow();
    await signIn(page, PARENT_EMAIL, PARENT_PASSWORD, /\/parent\/payments/);
    await page.goto("/parent/waivers");
    await expect(page.getByTestId("parent-waivers")).toBeVisible();
    await page.goto("/parent/attendance");
    await expect(page.getByTestId("parent-attendance")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Attendance" })).toBeVisible();
  });
});

async function signIn(page: Page, email: string, password: string, homeUrl: RegExp) {
  await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
  await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(homeUrl, { timeout: 90_000 });
}
