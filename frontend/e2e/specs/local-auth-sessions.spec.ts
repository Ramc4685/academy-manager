import { expect, test, type Page } from "@playwright/test";

// Real-auth verification of the #467 / #503 fixes against local SaaS staging
// seed data. Unlike the stubbed admin-shell specs, this signs in as the seeded
// BLno admin and drives the real backend, so it proves the fixes end to end.
//
// Run:
//   scripts/dev/saas_staging.sh up
//   scripts/dev/saas_staging.sh blno-seed
//   eval "$(scripts/dev/saas_staging.sh local-auth-env)"
//   LOCAL_AUTH_E2E=1 pnpm exec playwright test -c playwright.local-auth.config.ts

const LOCAL_AUTH_ENABLED = process.env.LOCAL_AUTH_E2E === "1";
const ADMIN_EMAIL = process.env.LOCAL_AUTH_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.LOCAL_AUTH_ADMIN_PASSWORD ?? "";
const SESSION_ID = process.env.LOCAL_AUTH_ADMIN_SESSION_ID ?? "";

test.describe("local authenticated admin session fixes", () => {
  test.skip(
    !LOCAL_AUTH_ENABLED,
    "Set LOCAL_AUTH_E2E=1 and run against approved local SaaS staging seed data.",
  );
  test.slow();

  test("#503: Add to roster opens instead of crashing the page", async ({ page }) => {
    test.skip(!SESSION_ID, "LOCAL_AUTH_ADMIN_SESSION_ID is required.");
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);

    await page.goto(`/admin/sessions/${SESSION_ID}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("admin-session-detail")).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: "Add to roster" }).click();

    // Before the fix an orphaned Radix Dialog.Close threw during render and the
    // whole page was replaced by the root error boundary.
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enroll" })).toBeVisible({ timeout: 15_000 });

    // The Cancel button is the exact element that used to throw — it must now
    // close the dialog rather than take the page down.
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByRole("button", { name: "Enroll" })).toHaveCount(0);
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
  });

  test("#467: cancelling a session removes it from the upcoming list", async ({ page }) => {
    await signIn(page, ADMIN_EMAIL, ADMIN_PASSWORD, /\/admin/);

    await page.goto("/admin/sessions", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("admin-sessions")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("admin-sessions-table")).toBeVisible({ timeout: 30_000 });

    // The admin shell finishes its Firebase auth check a beat after first paint
    // and hard-navigates the current route, which tears down any dialog that is
    // already open. Let the page go quiet before starting a multi-step form.
    await page.waitForLoadState("networkidle");

    // Cancel is destructive and irreversible, so the test cancels a session it
    // creates itself. That keeps the BLno seed intact and the spec re-runnable.
    const title = `E2E cancel probe ${Date.now()}`;
    await createSession(page, title);

    const cancelButton = page.getByRole("button", { name: `Cancel session ${title}` });
    await expect(cancelButton).toBeVisible({ timeout: 30_000 });
    const before = await countSessionRows(page);
    expect(before).toBeGreaterThan(0);

    page.once("dialog", (d) => void d.accept());
    await cancelButton.click();

    // Before the fix the row stayed put: the backend soft-cancelled but the
    // listing had no status predicate, so the refetch re-emitted the cancelled
    // session and the table repainted an identical row.
    await expect(cancelButton).toHaveCount(0, { timeout: 30_000 });
    await expect.poll(() => countSessionRows(page), { timeout: 30_000 }).toBe(before - 1);

    // And no error banner: this was a success, not a swallowed failure.
    await expect(page.getByTestId("admin-sessions-cancel-error")).toHaveCount(0);

    // The teeth of the regression: a full reload refetches from the backend, so
    // a listing that still returns cancelled sessions fails here even though the
    // in-memory table looked correct.
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("admin-sessions-table")).toBeVisible({ timeout: 30_000 });
    await expect(cancelButton).toHaveCount(0);
  });
});

async function createSession(page: Page, title: string) {
  await page.getByTestId("admin-sessions-create").click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Create session" })).toBeVisible();

  // The Coach field is a dropdown only once the admin directory resolves; while
  // it is loading — or if it fails — the form falls back to a free-text coach
  // reference, which the create endpoint accepts as-is. Wait for whichever of
  // the two settles so a directory outage cannot make this spec flaky.
  const coach = dialog.getByLabel("Coach");
  await expect(coach).not.toHaveAttribute("placeholder", "Loading coaches…", {
    timeout: 30_000,
  });
  if (await coach.evaluate((el) => el.tagName === "SELECT")) {
    await coach.selectOption({ index: 1 });
  } else {
    await coach.fill("e2e-coach-reference");
  }

  await dialog.getByLabel("Name").fill(title);
  await dialog.getByLabel("Location").fill("E2E Court");
  await dialog.getByLabel("Capacity").fill("4");
  await dialog.getByLabel("Monthly fee").fill("10");

  await dialog.getByRole("button", { name: "Create" }).click();
  await expect(dialog).toHaveCount(0, { timeout: 30_000 });
}

async function countSessionRows(page: Page): Promise<number> {
  // The table body only exists once the query resolves — while it is loading a
  // skeleton renders instead, so a `tbody tr` count silently reads 0.
  return page.locator('[data-testid^="session-row-"]').count();
}

async function signIn(page: Page, email: string, password: string, homeUrl: RegExp) {
  await page.goto("/login", { waitUntil: "domcontentloaded", timeout: 90_000 });
  await expect(page.getByTestId("login-submit")).toBeEnabled({ timeout: 90_000 });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByTestId("login-submit").click();
  await page.waitForURL(homeUrl, { timeout: 90_000 });
}
