import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Issue #713 — the roster row's "More actions" menu.
 *
 * The action column is `sticky right-0 z-10`, which makes every action cell its
 * own stacking context. While the menu rendered inside that cell, row N's open
 * menu painted UNDER row N+1's action cell: clicking "Transfer" on the first of
 * several rows actually hit the row below, and only the last menu item was
 * reachable. The menu is now portalled to `document.body`.
 *
 * "Pathway" moved from a standalone button beside the kebab into the menu, so a
 * roster row shows one control instead of two.
 */

const ACADEMY = "academy-e2e";
const SESSION_ID = "sess-713";

const ADMIN_ME = {
  user_id: "user-admin-713-e2e",
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

function occurrence(index: number, daysFromNow: number) {
  const start = new Date(Date.now() + daysFromNow * 86400000).toISOString();
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

const OCCURRENCES = [-7, 7, 14].map((days, index) => occurrence(index + 1, days));

// Six active rows: enough that the first row's open menu is spanned by several
// later action cells, which is exactly the situation the old markup broke on.
const ENROLLMENTS = ["Ana", "Bo", "Cy", "Dee", "Eli", "Fay"].map((name, index) => ({
  enrollment_id: `enr-${index + 1}`,
  session_id: SESSION_ID,
  student_id: `stu-${index + 1}`,
  parent_id: `parent-${index + 1}`,
  full_name: `${name} Roster`,
  status: "active",
  enrolled_at: "2026-08-01T00:00:00Z",
  dues_status: "current",
  pathway_program_id: "prog-1",
}));

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
        enrolled_count: ENROLLMENTS.length,
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
    if (request.method() === "GET" && path === "/api/v2/admin/programs/prog-1/pathway") {
      return fulfillJson(route, { program: null, levels: [] });
    }
    if (request.method() === "GET" && path === "/api/v2/admin/users") {
      return fulfillJson(route, { users: [] });
    }
    if (request.method() === "GET") return fulfillJson(route, {});
    return route.fallback();
  });
}

test.describe("admin roster row overflow menu (#713)", () => {
  test.beforeEach(async ({ page }) => {
    await stubAdminShell(page);
    await stubSessionDetail(page);
    await page.goto(`/admin/sessions/${SESSION_ID}`);
    await expect(page.getByTestId("enrollment-row-enr-1")).toBeVisible();
  });

  test("the first row's Transfer item opens the transfer dialog", async ({ page }) => {
    await page.getByRole("button", { name: "More actions for Ana Roster" }).click();
    await page.getByRole("menuitem", { name: "Transfer" }).click();

    await expect(page.getByRole("dialog")).toContainText("Transfer enrollment");
    await expect(page.getByRole("dialog")).toContainText("Ana Roster");
  });

  test("every item of the first row's menu is clickable, not just the last one", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "More actions for Ana Roster" }).click();
    await page.getByRole("menuitem", { name: "Pause" }).click();
    await expect(page.getByRole("dialog")).toContainText("Ana Roster");
  });

  test("Pathway is a link inside the menu, and no longer a standalone row button", async ({
    page,
  }) => {
    const row = page.getByTestId("enrollment-row-enr-1");
    await expect(row.getByRole("link", { name: "Pathway" })).toHaveCount(0);

    await page.getByRole("button", { name: "More actions for Ana Roster" }).click();
    const pathway = page.getByRole("menuitem", { name: "Pathway" });
    await expect(pathway).toBeVisible();

    const href = await pathway.getAttribute("href");
    const url = new URL(href ?? "", page.url());
    expect(url.pathname).toBe("/admin/students/stu-1/progress");
    expect(url.searchParams.get("program_id")).toBe("prog-1");
    expect(url.searchParams.get("return_to")).toBe(`/admin/sessions/${SESSION_ID}`);
    expect(url.searchParams.get("return_label")).toBe("Back to session");
  });

  test("keyboard opens the menu, and Escape closes it and returns focus to the trigger", async ({
    page,
  }) => {
    const trigger = page.getByRole("button", { name: "More actions for Ana Roster" });
    await trigger.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menu")).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Pathway" })).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
});
