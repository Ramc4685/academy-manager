import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Issue #671 — an admin calls off ONE class date from the session page.
 *
 * Stub-based: the point is the admin's path from the date list to a confirmed
 * cancellation and the Cancelled chip that comes back, plus the exact body the
 * route receives (the reason reaches families verbatim, so it must not be
 * mangled on the way).
 */

const ADMIN_ME = {
  user_id: "user-admin-cancel-date-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin", "owner"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAdminShell(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "BLNO Badminton Academy",
          academy_slug: "academy-e2e",
          roles: ["admin", "owner"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    });
  });
  await page.route("**/api/v2/admin/academy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "BLNO Badminton Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    });
  });
}

function formatDateInput(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function nextThursdayDateInput(): string {
  const value = new Date();
  const daysUntilThursday = (4 - value.getDay() + 7) % 7 || 7;
  value.setDate(value.getDate() + daysUntilThursday);
  return formatDateInput(value);
}

test.describe("admin cancels one class date (#671)", () => {
  test("cancel dialog posts the reason and the date comes back Cancelled", async ({
    page,
  }) => {
    await stubAdminShell(page);
    const classDate = nextThursdayDateInput();
    const occurrenceId = `series-thu:${classDate}:18:00`;
    let cancelPayload: unknown = null;
    let cancelled = false;

    const occurrenceRow = () => ({
      occurrence_id: occurrenceId,
      session_id: "series-thu",
      start_at: `${classDate}T23:00:00Z`,
      end_at: `${classDate}T23:45:00Z`,
      status: cancelled ? "cancelled" : "scheduled",
      cancellation_reason: cancelled ? "gym flooded" : null,
      cancelled_at: cancelled ? `${classDate}T12:00:00Z` : null,
      scheduled_coach_id: "coach-scheduled",
      actual_coach_id: null,
      substitute_coach_id: null,
      attendance_marked_count: 0,
      attendance_marked_by: [],
      attendance_last_marked_at: null,
      coach_attendance: [],
    });

    // #671: a date that has already run. The domain guard refuses to cancel
    // it (409), so the page must not offer the action at all — and the status
    // column must not call it "Scheduled".
    const pastDate = formatDateInput(new Date(Date.now() - 14 * 86400000));
    const pastOccurrenceId = `series-thu:${pastDate}:18:00`;
    const pastRow = {
      occurrence_id: pastOccurrenceId,
      session_id: "series-thu",
      start_at: `${pastDate}T23:00:00Z`,
      end_at: `${pastDate}T23:45:00Z`,
      status: "scheduled",
      cancellation_reason: null,
      cancelled_at: null,
      scheduled_coach_id: "coach-scheduled",
      actual_coach_id: null,
      substitute_coach_id: null,
      attendance_marked_count: 0,
      attendance_marked_by: [],
      attendance_last_marked_at: null,
      coach_attendance: [],
    };

    await page.route("**/api/v2/admin/**", (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && url.pathname === "/api/v2/admin/sessions/series-thu") {
        return fulfillJson(route, {
          session_id: "series-thu",
          coach_id: "coach-scheduled",
          coach_name: "Scheduled Coach",
          title: "Thursday 6:00 PM Beginner",
          location: "Court 1",
          start_at: `${classDate}T23:00:00Z`,
          end_at: `${classDate}T23:45:00Z`,
          days_of_week: ["Thu"],
          start_time: "18:00",
          end_time: "18:45",
          timezone: "America/Chicago",
          capacity: 12,
          status: "scheduled",
          enrolled_count: 3,
          waitlist_count: 0,
        });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-thu/occurrences"
      ) {
        return fulfillJson(route, { occurrences: [pastRow, occurrenceRow()] });
      }
      if (
        request.method() === "POST" &&
        // The client percent-encodes the occurrence id (it carries colons),
        // so match on the decoded path.
        decodeURIComponent(url.pathname) ===
          `/api/v2/admin/session-occurrences/${occurrenceId}/cancel`
      ) {
        cancelPayload = request.postDataJSON();
        cancelled = true;
        return fulfillJson(route, {
          occurrence: occurrenceRow(),
          affected_enrollment_ids: ["enr-1", "enr-2", "enr-3"],
          roster_entries_removed: 0,
          makeups_reopened: 0,
          credits_issued: 3,
          billing_result: "credited=3,override=written",
          notified: true,
        });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-thu/enrollments"
      ) {
        return fulfillJson(route, { enrollments: [] });
      }
      if (
        request.method() === "GET" &&
        url.pathname === "/api/v2/admin/sessions/series-thu/waitlist"
      ) {
        return fulfillJson(route, { waitlist: [] });
      }
      if (request.method() === "GET" && url.pathname === "/api/v2/admin/users") {
        return fulfillJson(route, {
          users: [
            {
              user_id: "coach-scheduled",
              email: "scheduled@example.com",
              display_name: "Scheduled Coach",
              role: "coach",
              status: "active",
            },
          ],
        });
      }
      return route.fallback();
    });

    await page.goto("/admin/sessions/series-thu");

    await expect(page.getByRole("heading", { name: "Class dates" })).toBeVisible();
    await expect(page.getByTestId("occurrence-cancelled-chip")).toHaveCount(0);
    // The past date is listed, labelled Past, and offers no cancel action.
    await expect(page.getByTestId(`cancel-occurrence-${pastOccurrenceId}`)).toHaveCount(0);
    await expect(page.getByText("Past", { exact: true })).toBeVisible();

    await page.getByTestId(`cancel-occurrence-${occurrenceId}`).click();

    const confirm = page.getByTestId("confirm-cancel-occurrence");
    // The reason is mandatory: an empty one tells the family nothing.
    await expect(confirm).toBeDisabled();
    await page.getByLabel("Reason").fill("gym flooded");
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect.poll(() => cancelPayload).toEqual({
      reason: "gym flooded",
      notify: true,
    });
    await expect(page.getByTestId("occurrence-cancelled-chip")).toBeVisible();
    // A cancelled date cannot be cancelled again from the list.
    await expect(page.getByTestId(`cancel-occurrence-${occurrenceId}`)).toHaveCount(0);
  });
});
