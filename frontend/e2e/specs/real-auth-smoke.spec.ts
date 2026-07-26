import { expect, test } from "@playwright/test";

import { REAL_AUTH_USERS } from "../fixtures/real-auth-users";

/**
 * Minimal real-auth smoke: real Firebase email/password sign-in against the
 * local Auth emulator, through the actual login form, asserting the backend
 * `/api/v2/me` BFF call succeeds and the client-side persona redirect lands
 * on the right home. This is the only Playwright spec CI runs against a real
 * (emulator-backed) auth stack — everything else in CI uses the auth bypass.
 *
 * Does NOT exercise prod Firebase quirks (e.g. the enumeration-protection
 * behavior noted in PR #304) — the Auth Emulator does not reproduce those.
 */
test.describe("real-auth smoke", () => {
  test("admin signs in, /me resolves the admin persona, and lands on /admin", async ({
    page,
  }) => {
    const { admin } = REAL_AUTH_USERS;

    await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
    await page.getByLabel("Email").fill(admin.email);
    await page.getByLabel("Password").fill(admin.password);

    const meResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v2/me") && response.request().method() === "GET",
      { timeout: 30_000 },
    );
    await page.getByTestId("login-submit").click();

    const response = await meResponse;
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.roles).toContain("admin");

    await expect(page).toHaveURL(/\/admin/, { timeout: 30_000 });
    await expect(page.getByTestId("admin-dashboard")).toBeVisible({ timeout: 30_000 });
  });

  test("parent signs in, /me resolves the parent persona, and lands on /parent/payments", async ({
    page,
  }) => {
    const { parent } = REAL_AUTH_USERS;

    await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
    await page.getByLabel("Email").fill(parent.email);
    await page.getByLabel("Password").fill(parent.password);

    const meResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v2/me") && response.request().method() === "GET",
      { timeout: 30_000 },
    );
    await page.getByTestId("login-submit").click();

    const response = await meResponse;
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.roles).toContain("parent");

    await expect(page).toHaveURL(/\/parent\/payments/, { timeout: 30_000 });
    await expect(page.getByTestId("parent-payments")).toBeVisible({ timeout: 30_000 });
  });

  test("unauthenticated visit to /admin redirects to /login", async ({ page }) => {
    await page.goto("/admin", { waitUntil: "domcontentloaded", timeout: 90_000 });
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
  });
});
