import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Admin Inbox "Attendance" tab: class dates nobody marked (one tap from the
 * coach marking screen) and marks changed after the fact (one tap from the
 * class date with Attendance open).
 * Stub-based; every name here is fake.
 */

const ADMIN_ME = {
  user_id: "admin-attendance-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const SESSION_ID = "sess-juniors";
const OCCURRENCE_ID = "sess-juniors:2026-11-18:16:00";
// 4pm Wednesday in Chicago; admins mark it as coach supervisors.
const MARK_HREF = `/coach/sessions/${encodeURIComponent(OCCURRENCE_ID)}?date=2026-11-18`;
const CORRECTED_ID = "occ-earlier";
const CORRECTION_HREF = `/admin/sessions/${SESSION_ID}?tab=dates&occurrence=${CORRECTED_ID}`;

const REVIEW = {
  missing: [
    {
      occurrence_id: OCCURRENCE_ID,
      session_id: SESSION_ID,
      session_name: "Juniors Tuesday",
      start_at: "2026-11-18T22:00:00Z",
      enrolled_count: 6,
    },
  ],
  corrections: [
    {
      attendance_id: "att-1",
      occurrence_id: CORRECTED_ID,
      session_id: SESSION_ID,
      session_name: "Juniors Tuesday",
      start_at: "2026-11-11T22:00:00Z",
      student_name: "Test Kid Alpha",
      status: "voided",
      previous_status: "present",
      corrected_at: "2026-11-20T15:00:00Z",
      corrected_by_name: "Test Owner",
      reason: "Marked the wrong class",
      href: CORRECTION_HREF,
    },
  ],
};

const SESSION = {
  session_id: SESSION_ID,
  coach_id: "coach-1",
  coach_name: "Test Coach",
  title: "Juniors Tuesday",
  location: "Court 1",
  start_at: "2026-09-01T22:00:00Z",
  end_at: "2026-09-01T23:00:00Z",
  days_of_week: ["Tue"],
  start_time: "16:00",
  end_time: "17:00",
  timezone: "America/Chicago",
  capacity: 12,
  status: "scheduled",
  enrolled_count: 6,
  waitlist_count: 0,
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function occurrenceRow(occurrenceId: string, startAt: string) {
  return {
    occurrence_id: occurrenceId,
    session_id: SESSION_ID,
    start_at: startAt,
    end_at: startAt.replace("22:00", "23:00"),
    status: "scheduled",
    cancellation_reason: null,
    cancelled_at: null,
    scheduled_coach_id: "coach-1",
    actual_coach_id: null,
    substitute_coach_id: null,
    attendance_marked_count: 0,
    attendance_marked_by: [],
    attendance_last_marked_at: null,
    coach_attendance: [],
  };
}

async function stubAdmin(page: Page) {
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
  await page.route("**/api/v2/admin/**", (route) => {
    const request = route.request();
    if (request.method() !== "GET") return route.fallback();
    const path = decodeURIComponent(new URL(request.url()).pathname);
    switch (path) {
      case "/api/v2/admin/inbox/counts":
        return fulfillJson(route, { counts: { attendance: 1 }, total: 1, unavailable: [] });
      case "/api/v2/admin/inbox/attendance":
        return fulfillJson(route, REVIEW);
      case "/api/v2/admin/messages":
        return fulfillJson(route, { messages: [] });
      case "/api/v2/admin/academy":
        return fulfillJson(route, {
          academy_id: "academy-e2e",
          display_name: "Rally Academy",
          timezone: "America/Chicago",
          contact_email: null,
          contact_phone: null,
          hours_text: null,
          address: null,
          logo_url: null,
          brand_color: null,
        });
      case "/api/v2/admin/sessions":
        return fulfillJson(route, { sessions: [{ ...SESSION, amount_cents: 0, not_billed_count: 0 }] });
      case `/api/v2/admin/sessions/${SESSION_ID}`:
        return fulfillJson(route, {
          session_id: SESSION_ID,
          coach_id: "coach-1",
          coach_name: "Test Coach",
          title: "Juniors Tuesday",
          location: "Court 1",
          start_at: "2026-09-01T22:00:00Z",
          end_at: "2026-09-01T23:00:00Z",
          days_of_week: ["Tue"],
          start_time: "16:00",
          end_time: "17:00",
          timezone: "America/Chicago",
          capacity: 12,
          status: "scheduled",
          enrolled_count: 6,
          waitlist_count: 0,
        });
      case `/api/v2/admin/sessions/${SESSION_ID}/occurrences`:
        // Many dates, so the linked one sits outside the default window.
        return fulfillJson(route, {
          occurrences: [
            occurrenceRow(CORRECTED_ID, "2026-11-11T22:00:00Z"),
            occurrenceRow(OCCURRENCE_ID, "2026-11-18T22:00:00Z"),
            ...Array.from({ length: 10 }, (_, i) => {
              const day = String(i + 1).padStart(2, "0");
              return occurrenceRow(`${SESSION_ID}:2027-01-${day}`, `2027-01-${day}T22:00:00Z`);
            }),
          ],
        });
      case `/api/v2/admin/session-occurrences/${CORRECTED_ID}/attendance`:
        return fulfillJson(route, {
          attendance: [
            {
              attendance_id: "att-1",
              occurrence_id: CORRECTED_ID,
              session_id: SESSION_ID,
              student_id: "stu-1",
              status: "voided",
              previous_status: "present",
              corrected_by: "admin-attendance-e2e",
              corrected_at: "2026-11-20T15:00:00Z",
              correction_reason: "Marked the wrong class",
              marked_by: "coach-1",
              marked_at: "2026-11-11T22:05:00Z",
            },
          ],
        });
      case `/api/v2/admin/sessions/${SESSION_ID}/enrollments`:
        return fulfillJson(route, { enrollments: [] });
      case `/api/v2/admin/sessions/${SESSION_ID}/waitlist`:
        return fulfillJson(route, { waitlist: [] });
      case "/api/v2/admin/users":
        return fulfillJson(route, { users: [] });
      default:
        return route.fallback();
    }
  });
}

test("attendance tab links missing dates to marking and corrections to the class date", async ({
  page,
}) => {
  await stubAdmin(page);
  await page.goto("/admin/inbox?tab=attendance");

  await expect(page.getByTestId("admin-inbox-count-attendance")).toHaveText("1");
  const missing = page.getByTestId(`admin-attendance-missing-${OCCURRENCE_ID}`);
  await expect(missing.getByText("Juniors Tuesday")).toBeVisible();
  await expect(missing.getByText("6 students on the roster, no marks")).toBeVisible();
  await expect(page.getByTestId(`admin-attendance-missing-link-${OCCURRENCE_ID}`)).toHaveAttribute(
    "href",
    MARK_HREF,
  );

  const correction = page.getByTestId("admin-attendance-correction-att-1");
  await expect(correction.getByText("Test Kid Alpha")).toBeVisible();
  await expect(correction.getByText("Reason: Marked the wrong class")).toBeVisible();
  await expect(page.getByTestId("admin-attendance-correction-link-att-1")).toHaveAttribute(
    "href",
    CORRECTION_HREF,
  );

  // The tab fits a phone: no sideways scroll.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  await page.getByTestId("admin-attendance-correction-link-att-1").click();

  await expect(page).toHaveURL(CORRECTION_HREF);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Attendance", { exact: true })).toBeVisible();
  await expect(dialog.getByTestId("attendance-status-stu-1")).toHaveText("voided");
});

// Usability study: an admin opened a recurring class template and guessed the
// weekday from a requested date. The list points to Class dates, and each date
// row names its weekday and year.
for (const viewport of [
  { name: "phone", size: { width: 400, height: 860 } },
  { name: "desktop", size: { width: 1280, height: 800 } },
]) test(`the sessions list leads to one class date, labelled with weekday and year (${viewport.name})`, async ({
  page,
}) => {
  await page.setViewportSize(viewport.size);
  await stubAdmin(page);
  await page.goto("/admin/sessions");
  await expect(page.getByTestId("sessions-dates-hint")).toContainText("regular schedule");
  const row = page.getByTestId(`session-row-${SESSION_ID}`);
  if (viewport.name === "desktop") {
    await expect(page.getByTestId("admin-sessions-table").getByText("Regular days")).toBeVisible();
  } else {
    await expect(row).toContainText("Regular: ");
  }
  const datesLink = page.getByTestId(`session-dates-link-${SESSION_ID}`);
  if (await datesLink.count()) {
    await expect(datesLink).toHaveAttribute("href", `/admin/sessions/${SESSION_ID}?tab=dates`);
    await datesLink.click();
  } else {
    // Phone layout: the same destination sits in the row's actions menu.
    await page.getByTestId(`session-actions-${SESSION_ID}`).click();
    await page.getByRole("menuitem", { name: "Class dates" }).click();
  }
  await expect(page).toHaveURL(new RegExp(`/admin/sessions/${SESSION_ID}\\?tab=dates`));
  await expect(page.getByTestId(`class-date-row-${OCCURRENCE_ID}`)).toContainText(
    "Wed, Nov 18, 2026",
  );
});
