/**
 * S17: reporting an absence asks for a second look that names the child,
 * class and date, sends no free-text reason, and leaves the date marked as
 * reported. Mocks the v2 BFF at the Playwright route layer. Names are fake.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const KID = "st-1";
const START = new Date(Date.now() + 3 * 86_400_000).toISOString();
const END = new Date(Date.now() + 3 * 86_400_000 + 3_600_000).toISOString();

function json(route: Route, body: unknown) {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubParent(page: Page, posted: unknown[]): Promise<void> {
  await page.route("**/api/v2/me", (route) =>
    route.request().method() !== "GET"
      ? route.fallback()
      : json(route, {
          user_id: "user-parent-e2e",
          email: "parent@example.com",
          academy_id: "academy-e2e",
          roles: ["parent"],
        }),
  );
  await page.route("**/api/v2/parent/academy", (route) =>
    json(route, {
      display_name: "Test Racquet Club",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
    }),
  );
  await page.route("**/api/v2/parent/registrations", (route) => json(route, { registrations: [] }));
  await page.route("**/api/v2/parent/attendance", (route) => json(route, { records: [] }));
  await page.route("**/api/v2/parent/enrollments", (route) => json(route, { enrollments: [] }));
  await page.route("**/api/v2/parent/children", (route) =>
    json(route, {
      children: [
        {
          student_id: KID,
          full_name: "Mira Testwell",
          lifecycle: "active",
          active_session_count: 1,
          attended_count: 0,
          absent_count: 0,
        },
      ],
    }),
  );
  await page.route(`**/api/v2/parent/children/${KID}/schedule*`, (route) =>
    json(route, {
      entries: [
        {
          occurrence_id: "occ-1",
          session_id: "sess-1",
          session_title: "Junior Beginners",
          location: "Court 2",
          start_at: START,
          end_at: END,
          status: "scheduled",
          coach_name: null,
          source: "regular",
          absence_reported: false,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    }),
  );
  await page.route("**/api/v2/parent/absences", (route) => {
    if (route.request().method() === "POST") {
      posted.push(JSON.parse(route.request().postData() ?? "{}"));
      return json(route, {
        notice_id: "n-1",
        student_id: KID,
        occurrence_id: "occ-1",
        session_id: "sess-1",
        submitted_by: "user-parent-e2e",
        submitted_at: new Date().toISOString(),
        notice_window_met: true,
      });
    }
    return json(route, { notices: [] });
  });
}

test.describe("S17 report absence", () => {
  test("confirm names the child and class, then the date reads reported", async ({ page }) => {
    const posted: unknown[] = [];
    await stubParent(page, posted);
    await page.goto("/parent/children");

    await page.getByRole("button", { name: "Report absence" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Mira");
    await expect(dialog).toContainText("Junior Beginners");
    await expect(dialog.getByRole("textbox")).toHaveCount(0);
    await dialog.getByRole("button", { name: "Report absence" }).click();

    await expect(page.getByTestId("absence-reported-occ-1")).toContainText("Absence reported");
    expect(posted).toEqual([{ student_id: KID, occurrence_id: "occ-1" }]);
  });
});
