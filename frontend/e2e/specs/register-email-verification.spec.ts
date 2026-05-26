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

    await page.goto("/register");
    await expect(page.getByTestId("register-submit")).toBeEnabled();
    await page.getByTestId("register-email").fill("parent@example.com");
    await expect(page.getByTestId("register-email")).toHaveValue("parent@example.com");
    await page.getByTestId("register-password").fill("correct-horse-1");
    await expect(page.getByTestId("register-password")).toHaveValue("correct-horse-1");
    await page.getByTestId("register-submit").click();

    await expect(page.getByRole("status")).toContainText("Account created");
    await expect(page.getByRole("button", { name: "Send verification email" })).toBeVisible();
    expect(parentRegistrationCalls).toBe(1);
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
    expect(parentRegistrationCalls).toBe(1);
  });
});
