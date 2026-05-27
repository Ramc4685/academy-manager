import { expect, test, type Page } from "@playwright/test";

const LOCAL_AUTH_ENABLED = process.env.LOCAL_AUTH_E2E === "1";

const PARENT_EMAIL = process.env.LOCAL_AUTH_PARENT_EMAIL ?? "manojedward.btech@gmail.com";
const PARENT_PASSWORD = process.env.LOCAL_AUTH_PARENT_PASSWORD ?? "Parent@12345";
const ADMIN_EMAIL = process.env.LOCAL_AUTH_ADMIN_EMAIL ?? "ramchand4685@gmail.com";
const ADMIN_PASSWORD = process.env.LOCAL_AUTH_ADMIN_PASSWORD ?? "Admin@12345";
const COACH_EMAIL = process.env.LOCAL_AUTH_COACH_EMAIL ?? "gowtham@blno.academy";
const COACH_PASSWORD = process.env.LOCAL_AUTH_COACH_PASSWORD ?? "Coach@12345";

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
    const portalRequest = page.waitForRequest(/https:\/\/fake\.stripe\.com\/portal\//);
    await page.getByRole("button", { name: "Billing portal" }).click({ noWaitAfter: true });
    await expect((await portalRequest).url()).toContain("fake.stripe.com/portal/");

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
});

async function signIn(page: Page, email: string, password: string, homeUrl: RegExp) {
  await page.goto("/login");
  await expect(page.getByTestId("login-submit")).toBeEnabled();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(homeUrl);
}
