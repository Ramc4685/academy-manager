/**
 * Coach shell header must fit a phone (#745).
 *
 * An academy admin covering a session (#632) opens a session detail page, so
 * the header carries the back button, the persona switcher AND — the moment
 * the phone drops offline, which is exactly the scenario the session page is
 * built for — the Offline chip. Before the fix that row was a single
 * no-wrap flex line: the document gained horizontal scroll and the Log out
 * button sat past the right edge of a 390px viewport.
 */

import { test, expect } from "../fixtures/mock-api";

const VIEWPORT = { width: 390, height: 844 };

test.use({ viewport: VIEWPORT });

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(
    metrics.scrollWidth,
    `document scrollWidth ${metrics.scrollWidth} exceeds viewport ${metrics.clientWidth}`,
  ).toBeLessThanOrEqual(metrics.clientWidth);
}

async function expectWithinViewport(locator: import("@playwright/test").Locator) {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "element has a layout box").not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(VIEWPORT.width);
}

test.describe("Coach shell header on a phone (#745)", () => {
  test("admin covering a session keeps Log out on-screen, online and offline", async ({
    page,
    mock,
  }) => {
    // Admin + coach: the persona switcher renders next to the shell icons.
    mock.me.roles = ["admin", "coach"];

    // A session detail page is not a top-level coach route, so the shell
    // also renders the back button.
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("shell-back-button")).toBeVisible();
    await expect(page.getByTestId("persona-switcher-button")).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectWithinViewport(page.getByTestId("persona-logout-button"));

    // Going offline adds the Offline chip to the same row.
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByText("Offline", { exact: true })).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectWithinViewport(page.getByTestId("persona-logout-button"));
  });
});
