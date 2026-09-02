import { expect, test } from "@playwright/test";

test.describe("parent email registration verification", () => {
  test("keeps a resend path when verification email fails after account creation", async ({
    page,
  }) => {
    test.slow();
    let parentRegistrationCalls = 0;
    // The verification email is sent by OUR backend (branded, our Resend
    // domain), not by Firebase's client SDK. Counting the calls is what keeps
    // this spec honest: a regression that skips the request entirely would
    // otherwise still show "Verification email sent" and pass.
    const verificationEmailCalls: { authorization: string | undefined }[] = [];

    await page.route(
      "**/api/v2/register/parent/verification-email",
      (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        verificationEmailCalls.push({
          authorization: route.request().headers()["authorization"],
        });
        return route.fulfill({ status: 204, body: "" });
      },
    );

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
    await expect(page.getByTestId("register-email")).toHaveValue(
      "parent@example.com",
    );
    await page.getByTestId("register-password").fill("correct-horse-1");
    await expect(page.getByTestId("register-password")).toHaveValue(
      "correct-horse-1",
    );
    await page.getByTestId("register-submit").click();

    await expect(page.getByRole("status")).toContainText("Account created");
    await expect(
      page.getByRole("button", { name: "Send verification email" }),
    ).toBeVisible();
    expect(parentRegistrationCalls).toBe(0);
    // The first attempt failed before a token existed, so nothing should have
    // reached the backend — the failure notice is not a swallowed send.
    expect(verificationEmailCalls).toHaveLength(0);
    await expect
      .poll(() =>
        page.evaluate(
          () => window.__E2E_FIREBASE__?.verificationFailuresRemaining ?? null,
        ),
      )
      .toBe(0);

    await page.getByRole("button", { name: "Send verification email" }).click();

    await expect(page.getByRole("status")).toContainText(
      "Verification email sent",
    );
    // "Verification email sent" is only true if the backend was actually asked
    // to send it, with the user's bearer token attached.
    await expect.poll(() => verificationEmailCalls.length).toBe(1);
    expect(verificationEmailCalls[0].authorization).toMatch(/^Bearer .+/);
    await expect(
      page.getByRole("button", { name: "Send verification email" }),
    ).toBeHidden();

    await expect(page.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
    await Promise.all([
      page.waitForURL(/\/login$/, { timeout: 15000 }),
      page.evaluate(() => window.location.assign("/login")),
    ]);
    await expect(page.getByTestId("login-submit")).toBeEnabled();
    await page.getByTestId("login-email").fill("parent@example.com");
    await page.getByTestId("login-password").fill("correct-horse-1");
    await page.getByTestId("login-submit").click();

    await expect(page).toHaveURL(/\/parent\/onboarding$/, { timeout: 15000 });
    await expect(page.getByTestId("parent-onboarding")).toBeVisible();
    expect(parentRegistrationCalls).toBe(1);
  });
});
