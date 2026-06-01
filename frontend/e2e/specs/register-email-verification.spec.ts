import { expect, test } from "@playwright/test";

test.describe("parent email registration verification", () => {
  test("keeps a resend path when verification email fails after account creation", async ({
    page,
  }) => {
    let parentRegistrationCalls = 0;

    await page.addInitScript(() => {
      window.__E2E_FIREBASE__ = { verificationFailuresRemaining: 1 };
    });

    await page.route("**/api/v2/register/parent", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      parentRegistrationCalls += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "parent-user-1",
          email: "parent@example.com",
          academy_id: "academy-e2e",
          roles: ["parent"],
        }),
      });
    });
    await page.route("**/api/v2/me", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "parent-user-1",
          email: "parent@example.com",
          academy_id: "academy-e2e",
          roles: ["parent"],
        }),
      });
    });
    await page.route("**/api/v2/parent/onboarding/start", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          application_id: "app-register-1",
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
          expires_at: "2026-06-08T00:00:00Z",
        }),
      });
    });
    await page.route("**/api/v2/parent/sessions/available", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sessions: [] }),
      });
    });

    await page.goto("/register");
    await expect(page.getByTestId("register-submit")).toBeEnabled();
    await page.getByTestId("register-email").fill("parent@example.com");
    await expect(page.getByTestId("register-email")).toHaveValue("parent@example.com");
    await page.getByTestId("register-password").fill("correct-horse-1");
    await expect(page.getByTestId("register-password")).toHaveValue("correct-horse-1");
    await page.getByTestId("register-submit").click();

    await expect(page.getByRole("status")).toContainText("Account created");
    await expect(page.getByRole("button", { name: "Send verification email" })).toBeVisible();
    expect(parentRegistrationCalls).toBe(0);
    await expect
      .poll(() =>
        page.evaluate(
          () => window.__E2E_FIREBASE__?.verificationFailuresRemaining ?? null
        )
      )
      .toBe(0);

    await page.getByRole("button", { name: "Send verification email" }).click();

    await expect(page.getByRole("status")).toContainText("Verification email sent");
    await expect(
      page.getByRole("button", { name: "Send verification email" })
    ).toBeHidden();

    await page.goto("/login");
    await page.getByTestId("login-email").fill("parent@example.com");
    await page.getByTestId("login-password").fill("correct-horse-1");
    await page.getByTestId("login-submit").click();

    await expect(page).toHaveURL(/\/parent\/onboarding$/, { timeout: 15000 });
    await expect(page.getByTestId("parent-onboarding")).toBeVisible();
    expect(parentRegistrationCalls).toBe(1);
  });
});
