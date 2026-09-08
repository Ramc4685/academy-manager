/**
 * Issue #673: the Level-ups tab respects enrollment lifecycle.
 *
 * A student recommended while enrolled and then withdrawn stays in the queue
 * (so the admin can reject) but is flagged and cannot be approved; a 409
 * `StudentProgress.EnrollmentEnded` from the backend (withdrawn after the
 * queue loaded) surfaces as a readable message.
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "admin-level-ups-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const LIVE_REC = {
  rec_id: "rec-live",
  student_id: "st-live",
  from_level_id: "lvl-1",
  to_level_id: "lvl-2",
  program_id: "prog-1",
  status: "RECOMMENDED",
  recommended_by: "coach-1",
  recommended_at: "2026-08-20T09:00:00Z",
  enrollment_active: true,
};

const WITHDRAWN_REC = {
  ...LIVE_REC,
  rec_id: "rec-gone",
  student_id: "st-gone",
  enrollment_active: false,
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page) {
  await page.route("**/api/v2/me", (route) => fulfillJson(route, ADMIN_ME));
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Rally Academy",
          academy_slug: "academy-e2e",
          roles: ["admin"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  // Catch-all first (LIFO matching): unstubbed admin GETs return {} instead
  // of hitting a backend that is not running.
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
  await page.route("**/api/v2/admin/academy", (route) =>
    fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Rally Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    }),
  );
  // The admin shell polls the inbox on every page.
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [] }),
  );
  await page.route("**/api/v2/admin/registrations*", (route) =>
    fulfillJson(route, { registrations: [] }),
  );
  await page.route("**/api/v2/admin/waitlist", (route) =>
    fulfillJson(route, { total_waitlisted: 0, sessions: [] }),
  );
}

test("withdrawn student is flagged and cannot be approved, live student can", async ({
  page,
}) => {
  await stubAdminShell(page);
  await page.route("**/api/v2/admin/level-up-queue*", (route) =>
    fulfillJson(route, { queue: [LIVE_REC, WITHDRAWN_REC] }),
  );

  await page.goto("/admin/registrations?tab=level-ups");
  await expect(page.getByTestId("admin-level-up-queue-tab")).toBeVisible();

  const gone = page.getByTestId("level-up-row-rec-gone");
  await expect(gone.getByTestId("level-up-withdrawn-rec-gone")).toBeVisible();
  await expect(gone.getByText("Withdrawn")).toBeVisible();
  await expect(gone.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  // Reject stays available so the admin can clear the row.
  await expect(gone.getByRole("button", { name: "Reject", exact: true })).toBeEnabled();

  const live = page.getByTestId("level-up-row-rec-live");
  await expect(live.getByTestId("level-up-withdrawn-rec-live")).toHaveCount(0);
  await expect(live.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();
});

test("approve refused by the backend after a withdrawal shows the lifecycle message", async ({
  page,
}) => {
  await stubAdminShell(page);
  // The queue was read before the family withdrew: the row still looks live.
  await page.route("**/api/v2/admin/level-up-queue*", (route) =>
    fulfillJson(route, { queue: [LIVE_REC] }),
  );
  await page.route("**/api/v2/admin/level-up/rec-live/approve", (route) =>
    fulfillJson(
      route,
      {
        error: {
          code: "StudentProgress.EnrollmentEnded",
          message: "student no longer has an active or paused enrollment",
          details: { rec_id: "rec-live", student_id: "st-live" },
        },
      },
      409,
    ),
  );

  await page.goto("/admin/registrations?tab=level-ups");
  const live = page.getByTestId("level-up-row-rec-live");
  await live.getByRole("button", { name: "Approve", exact: true }).click();

  const alert = page.getByTestId("level-up-review-error");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/withdrawn/i);
  await expect(alert).toContainText(/reject/i);
});
