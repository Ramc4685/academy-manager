/**
 * #895: the announcements composer is off the marking screen.
 *
 * The coach session page is where attendance gets marked, usually on a phone
 * between rallies. An always-open 3-row textarea, an urgency checkbox and a
 * "Post announcement" button sat under the roster on every visit, pushing the
 * thing the coach actually came for further from the thumb. The composer now
 * lives behind a disclosure and only the admin page keeps it open by default,
 * so nothing about the shared panel — or the attendance save path — changes.
 */

import { test, expect } from "../fixtures/mock-api";

test.describe("Coach session announcements composer (#895)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v2/coach/sessions/*/announcements", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ announcements: [] }),
      });
    });
  });

  test("the composer is collapsed until the coach asks for it", async ({
    page,
    mock,
  }) => {
    void mock;
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    // The roster — what the screen is for — is present without the composer.
    await expect(page.getByTestId("mark-st1-present")).toBeVisible();

    const toggle = page.getByTestId("announcements-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("announcement-body")).toHaveCount(0);
    await expect(page.getByTestId("announcement-post")).toHaveCount(0);

    await toggle.click();

    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("announcement-body")).toBeVisible();
    await expect(page.getByTestId("announcement-post")).toBeVisible();

    // And it closes again.
    await toggle.click();
    await expect(page.getByTestId("announcement-body")).toHaveCount(0);
  });
});
