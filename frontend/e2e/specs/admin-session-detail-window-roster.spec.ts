import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Issue #711 — the admin session page after the redesign.
 *
 *  - "Class dates" lists the 3 most recent past and the next 3 upcoming dates
 *    by default, with one toggle that expands to the full list.
 *  - The roster splits into Active / Past tabs; a paused student lives on Past
 *    and can be dropped from there, a withdrawn one cannot be dropped again.
 *  - RosterMetrics keep reading the FULL enrollment list, whichever tab is up.
 */

const ACADEMY = "academy-e2e";
const SESSION_ID = "sess-711";

const ADMIN_ME = {
  user_id: "user-admin-711-e2e",
  email: "admin@example.com",
  academy_id: ACADEMY,
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
          academy_id: ACADEMY,
          academy_name: "Academy E2E",
          academy_slug: ACADEMY,
          roles: ["admin", "owner"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: ACADEMY,
    });
  });
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [], unread_count: 0 }),
  );
}

function isoDaysFromNow(days: number): string {
  return new Date(Date.now() + days * 86400000).toISOString();
}

function occurrence(index: number, daysFromNow: number) {
  const start = isoDaysFromNow(daysFromNow);
  return {
    occurrence_id: `occ-${index}`,
    session_id: SESSION_ID,
    start_at: start,
    end_at: new Date(new Date(start).getTime() + 45 * 60000).toISOString(),
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

// 5 past (35..7 days ago) and 3 future (7..21 days out), in order.
const OCCURRENCES = [-35, -28, -21, -14, -7, 7, 14, 21].map((days, index) =>
  occurrence(index + 1, days),
);

function enrollment(id: string, name: string, status: string) {
  return {
    enrollment_id: id,
    session_id: SESSION_ID,
    student_id: `stu-${id}`,
    parent_id: `parent-${id}`,
    full_name: name,
    status,
    enrolled_at: "2026-08-01T00:00:00Z",
    dues_status: "current",
  };
}

const ENROLLMENTS = [
  enrollment("enr-active-1", "Ava Active", "active"),
  enrollment("enr-active-2", "Ben Active", "active"),
  enrollment("enr-paused", "Priya Paused", "paused"),
  enrollment("enr-withdrawn", "Wes Withdrawn", "withdrawn"),
];

async function stubSessionDetail(page: Page) {
  await page.route("**/api/v2/admin/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}`) {
      return fulfillJson(route, {
        session_id: SESSION_ID,
        coach_id: "coach-1",
        coach_name: "Coach One",
        title: "Tuesday 6:00 PM Beginner",
        location: "Court 1",
        start_at: OCCURRENCES[0].start_at,
        end_at: OCCURRENCES[0].end_at,
        days_of_week: ["Tue"],
        start_time: "18:00",
        end_time: "18:45",
        timezone: "America/Chicago",
        capacity: 12,
        amount_cents: 10000,
        status: "scheduled",
        enrolled_count: 2,
        waitlist_count: 0,
      });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/enrollments`) {
      return fulfillJson(route, { enrollments: ENROLLMENTS });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/occurrences`) {
      return fulfillJson(route, { occurrences: OCCURRENCES });
    }
    if (request.method() === "GET" && path === `/api/v2/admin/sessions/${SESSION_ID}/waitlist`) {
      return fulfillJson(route, { waitlist: [] });
    }
    if (request.method() === "GET" && path === "/api/v2/admin/users") {
      return fulfillJson(route, {
        users: [
          {
            user_id: "coach-1",
            email: "coach@example.com",
            display_name: "Coach One",
            role: "coach",
            status: "active",
          },
        ],
      });
    }
    if (request.method() === "GET") return fulfillJson(route, {});
    return route.fallback();
  });
}

/**
 * #857: below `md` the Class dates table is replaced by phone rows, so an
 * ancestor-of-a-`<table>` walk resolves nothing under chromium-mobile. Both
 * layouts tag each date `class-date-row-<occurrenceId>`, which is also the
 * document order the windowing assertions rely on.
 */
function classDateRows(page: Page) {
  return page.locator('[data-testid^="class-date-row-"]');
}

test.describe("admin session detail — class dates window and roster tabs (#711)", () => {
  test.beforeEach(async ({ page }) => {
    await stubAdminShell(page);
    await stubSessionDetail(page);
    await page.goto(`/admin/sessions/${SESSION_ID}`);
    // Roster is the first tab on every screen; Class dates is one click away.
    await expect(page.getByTestId("enrollment-row-enr-active-1")).toBeVisible();
  });

  async function openClassDates(page: Page) {
    await page.getByRole("button", { name: "Class dates", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Class dates" })).toBeVisible();
  }

  test("class dates default to 3 past + 3 upcoming and expand to the full list", async ({
    page,
  }) => {
    await openClassDates(page);
    const rows = classDateRows(page);
    await expect(rows).toHaveCount(6);
    // The two oldest past dates are windowed out; the newest 3 past and all 3
    // upcoming remain, still in chronological order.
    await expect(rows.nth(0)).toContainText("Past");
    await expect(rows.nth(2)).toContainText("Past");
    await expect(rows.nth(3)).toContainText("Scheduled");
    await expect(page.getByTestId("cancel-occurrence-occ-6")).toBeVisible();
    await expect(page.getByTestId("cancel-occurrence-occ-8")).toBeVisible();

    const toggle = page.getByTestId("class-dates-show-all");
    await expect(toggle).toHaveText("Show all 8 dates");
    await toggle.click();
    await expect(rows).toHaveCount(8);
    await expect(toggle).toHaveText("Show fewer");

    await toggle.click();
    await expect(rows).toHaveCount(6);
    await expect(toggle).toHaveText("Show all 8 dates");
  });

  test("roster splits active from past; paused can be dropped, withdrawn cannot", async ({
    page,
  }) => {
    const activeTab = page.getByRole("tab", { name: /Active/ });
    const pastTab = page.getByRole("tab", { name: /Past/ });
    await expect(activeTab).toHaveAttribute("aria-selected", "true");
    await expect(activeTab).toContainText("2");
    await expect(pastTab).toContainText("2");

    await expect(page.getByTestId("enrollment-row-enr-active-1")).toBeVisible();
    await expect(page.getByTestId("enrollment-row-enr-paused")).toHaveCount(0);
    await expect(page.getByTestId("enrollment-row-enr-withdrawn")).toHaveCount(0);

    await pastTab.click();
    await expect(pastTab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("enrollment-row-enr-active-1")).toHaveCount(0);
    await expect(page.getByTestId("enrollment-row-enr-paused")).toBeVisible();
    await expect(page.getByTestId("enrollment-row-enr-withdrawn")).toBeVisible();

    await page.getByRole("button", { name: "More actions for Priya Paused" }).click();
    await expect(page.getByRole("menuitem", { name: "Drop" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Resume" })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "More actions for Wes Withdrawn" }).click();
    await expect(page.getByRole("menuitem", { name: "Transfer" })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Drop" })).toHaveCount(0);
  });

  test("roster metrics read the full list whichever tab is showing", async ({ page }) => {
    const inSession = page.getByText("In session", { exact: true }).locator("..");
    await expect(inSession).toContainText("2");
    await expect(inSession).toContainText("1 paused");

    await page.getByRole("tab", { name: /Past/ }).click();
    await expect(page.getByTestId("enrollment-row-enr-paused")).toBeVisible();
    await expect(inSession).toContainText("2");
    await expect(inSession).toContainText("1 paused");

    // The page-level tabs still work around the nested roster tabs, and the
    // roster view survives the round trip.
    await page.getByRole("button", { name: "Waitlist", exact: true }).click();
    await expect(page.getByTestId("waitlist-empty")).toBeVisible();
    await page.getByRole("button", { name: "Roster", exact: true }).click();
    await expect(page.getByRole("tab", { name: /Past/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("enrollment-row-enr-paused")).toBeVisible();
  });

  /**
   * Most visits to this page are roster visits, so the Roster tab opens first
   * on every screen and the first student is within the first two screens.
   * Class dates, Waitlist, Teaching plan and Welcome email are tabs; Coaching
   * staff is a one-line strip under the header.
   */
  const PHONE = { width: 400, height: 800 };
  const DESKTOP = { width: 1280, height: 800 };

  for (const [label, viewport] of [
    ["at 400px", PHONE],
    ["on a desktop", DESKTOP],
  ] as const) {
    test(`${label} the roster opens first and its first row is within two screens`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      const firstRow = page.getByTestId("enrollment-row-enr-active-1");
      await expect(firstRow).toBeVisible();
      await expect(page.getByRole("heading", { name: "Roster", exact: true })).toBeVisible();
      // The setup panels are not stacked above the roster any more.
      await expect(page.getByRole("heading", { name: "Class dates" })).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Communication pack" })).toHaveCount(0);
      const firstRowTop = await firstRow.evaluate((el) => el.getBoundingClientRect().top + window.scrollY);
      expect(firstRowTop).toBeLessThan(2 * viewport.height);
    });
  }

  test("the tab strip lists Roster, Class dates, Waitlist, Teaching plan, Welcome email in order", async ({
    page,
  }) => {
    const labels = await page.locator('[data-testid^="session-tab-"]').allInnerTexts();
    expect(labels).toEqual(["Roster", "Class dates", "Waitlist", "Teaching plan", "Welcome email"]);
    await expect(page.getByTestId("session-staff")).toContainText("Coach One");
  });

  test.describe("Welcome email tab", () => {
    test("shows academy defaults in grey, and Save sends only the pack fields", async ({ page }) => {
      await page.route("**/api/v2/admin/academy", (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return fulfillJson(route, {
          academy_id: ACADEMY,
          display_name: "Academy E2E",
          default_class_size: 10,
          default_class_length_minutes: 45,
          default_venue_address: "123 Court St",
          default_parking_note: null,
          default_what_to_bring: null,
          default_arrival_minutes_before: 10,
          default_coach_contact_policy: null,
        });
      });
      await page.route("**/api/v2/admin/self-service/policy", (route) =>
        fulfillJson(route, { welcome_email_absence_policy_default: "Tell us 24 hours ahead" }),
      );
      const patches: Array<Record<string, unknown>> = [];
      await page.route(`**/api/v2/admin/sessions/${SESSION_ID}`, (route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        patches.push(JSON.parse(route.request().postData() ?? "{}"));
        return fulfillJson(route, {
          session_id: SESSION_ID,
          coach_id: "coach-1",
          coach_name: "Coach One",
          title: "Tuesday 6:00 PM Beginner",
          location: "Court 1",
          start_at: OCCURRENCES[0].start_at,
          end_at: OCCURRENCES[0].end_at,
          days_of_week: ["Tue"],
          start_time: "18:00",
          end_time: "18:45",
          timezone: "America/Chicago",
          capacity: 12,
          amount_cents: 10000,
          status: "scheduled",
          enrolled_count: 2,
          waitlist_count: 0,
          parking_notes: "Lot B",
        });
      });

      await page.getByRole("button", { name: "Welcome email", exact: true }).click();
      const venue = page.getByTestId("welcome-row-venue_address");
      await expect(venue).toContainText("123 Court St");
      await expect(venue).toContainText("(academy default)");
      await expect(page.getByTestId("welcome-row-arrival_minutes_before")).toContainText(
        "10 minutes before start",
      );
      await expect(page.getByTestId("welcome-row-absence_policy")).toContainText(
        "Tell us 24 hours ahead",
      );
      await expect(page.getByTestId("welcome-row-parking_notes")).toContainText("Not set");
      await expect(page.getByTestId("welcome-email-save")).toBeDisabled();

      await page.getByTestId("welcome-row-parking_notes-override").click();
      await page.getByTestId("welcome-input-parking_notes").fill("Lot B");
      await page.getByTestId("welcome-email-save").click();

      await expect.poll(() => patches.length).toBe(1);
      expect(patches[0]).toEqual({ parking_notes: "Lot B" });
    });
  });

  // #521: the page only needs coach names (for the replacement-coach table),
  // but used to fetch the entire tenant user directory on every load.
  test("fetches only coach-role users, not the full tenant directory", async ({ page }) => {
    const usersRequest = page.waitForRequest(
      (request) => request.method() === "GET" && request.url().includes("/api/v2/admin/users"),
    );
    await page.reload();
    const request = await usersRequest;
    expect(new URL(request.url()).searchParams.get("role")).toBe("coach");
  });
});
