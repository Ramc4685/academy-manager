/**
 * Parent shell header must fit a phone.
 *
 * With a logo_url and a long display_name, the title side of the header did
 * not shrink, so the icon group (calendar, messages, profile, log out) ran
 * past a 412px viewport and every parent page scrolled sideways.
 *
 * Synthetic data only. Runs on the mobile projects (Pixel 7 is 412px wide).
 */

import { test, expect } from "../fixtures/mock-api";
import type { Locator, Page, Route } from "@playwright/test";

const LOGO_URL = "https://logo.example.test/aces.svg";
const LOGO_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">' +
  '<rect width="64" height="64" rx="10" fill="#0f766e"/></svg>';

const CONTROLS = ["nav-calendar", "nav-messages", "nav-profile", "persona-logout-button"];

type Box = { x: number; y: number; width: number; height: number };

async function stubGet(page: Page, pattern: string, body: unknown): Promise<void> {
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

async function boxOf(locator: Locator): Promise<Box> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "element has a layout box").not.toBeNull();
  return box!;
}

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

for (const roles of [["parent"], ["parent", "coach"]]) {
  test(`parent header with a logo and a long name fits a phone (roles: ${roles.join("+")})`, async ({
    page,
  }) => {
    await stubGet(page, "**/api/v2/me", {
      user_id: "user-parent-e2e",
      email: "parent@example.com",
      academy_id: "academy-e2e",
      roles,
    });
    await stubGet(page, "**/api/v2/parent/messages", { messages: [] });
    await stubGet(page, "**/api/v2/parent/academy", {
      display_name: "Riverside Shuttle and Racquet Sports Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: LOGO_URL,
      brand_color: "#0f766e",
    });
    await page.route(LOGO_URL, (route) =>
      route.fulfill({ status: 200, contentType: "image/svg+xml", body: LOGO_SVG }),
    );

    // Not a top-level route, so the back button renders too.
    await page.goto("/parent/checkout/return");
    await expect(page.getByTestId("shell-back-button")).toBeVisible();

    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(
      metrics.scrollWidth,
      `document scrollWidth ${metrics.scrollWidth} exceeds viewport ${metrics.clientWidth}`,
    ).toBeLessThanOrEqual(metrics.clientWidth);

    // The logo keeps its full 32px box rather than being squeezed.
    const logo = await boxOf(page.locator("header img"));
    expect(logo.width).toBe(32);
    const title = await boxOf(page.locator("header a[href='/parent/dashboard']"));

    const width = page.viewportSize()!.width;
    for (const id of CONTROLS) {
      const control = await boxOf(page.getByTestId(id));
      expect(control.x + control.width, `${id} is past the right edge`).toBeLessThanOrEqual(width);
      expect(overlaps(control, title), `${id} overlaps the academy title`).toBe(false);
    }
  });
}
