/**
 * #1045 — Coach Sessions linked an evening class to its UTC date.
 *
 * America/Chicago, Nov 5 2026, 6:00 PM CST is 2026-11-06T00:00Z. The list
 * grouped the class under Thursday Nov 5 but linked `?date=2026-11-06`; the
 * session screen asks `/coach/today` for that date, the backend buckets by
 * session-local day (#510), the occurrence is absent, and the coach sees
 * "Session not found." This spec clicks the link the Sessions list actually
 * renders and checks the roster loads, then confirms Calendar links the same
 * occurrence to the same URL.
 */

import type { Route } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

const OCCURRENCE = {
  session_id: "sess-eve",
  occurrence_id: "occ-eve-1105",
  title: "Evening Juniors",
  location: "Court 2",
  timezone: "America/Chicago",
  start_at: "2026-11-06T00:00:00Z",
  end_at: "2026-11-06T01:00:00Z",
};

test.describe("Coach Sessions links use the class's local date (#1045)", () => {
  // Requesting `mock` installs the signed-in coach identity and shell stubs;
  // the routes below are registered after it, so they take precedence.
  test.beforeEach(async ({ page, mock }) => {
    void mock;
    await page.clock.setFixedTime(new Date("2026-10-01T15:00:00Z"));

    await page.route("**/api/v2/coach/sessions", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ sessions: [OCCURRENCE] }),
      });
    });

    // Mirrors the backend: occurrences are returned for their LOCAL date only.
    await page.route("**/api/v2/coach/today*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const date = new URL(route.request().url()).searchParams.get("date");
      const sessions =
        date === "2026-11-05"
          ? [
              {
                ...OCCURRENCE,
                roster: [
                  { student_id: "st-eve", full_name: "Evan Evening", enrollment_status: "active" },
                ],
              },
            ]
          : [];
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ date, sessions }),
      });
    });
  });

  test("the Sessions link opens the occurrence's roster", async ({ page }) => {
    await page.goto("/coach/sessions");
    const link = page.getByRole("link", { name: /Evening Juniors/ });
    await expect(link).toHaveAttribute(
      "href",
      "/coach/sessions/occ-eve-1105?date=2026-11-05",
    );

    await link.click();
    await expect(page).toHaveURL(/\/coach\/sessions\/occ-eve-1105\?date=2026-11-05$/);
    await expect(page.getByTestId("session-detail")).toContainText("Evan Evening");
    await expect(page.getByText("Session not found.")).toHaveCount(0);
  });

  test("Calendar links the same occurrence to the same URL", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.clock.setFixedTime(new Date("2026-11-05T15:00:00Z"));
    await page.goto("/coach/calendar");
    await expect(page.getByTestId("calendar-timezone")).toContainText("America/Chicago");
    const cell = page.locator('.fc-daygrid-day[data-date="2026-11-05"]');
    await cell.getByText("Evening Juniors").click();
    await expect(page).toHaveURL(/\/coach\/sessions\/occ-eve-1105\?date=2026-11-05$/);
    await expect(page.getByTestId("session-detail")).toContainText("Evan Evening");
  });
});
