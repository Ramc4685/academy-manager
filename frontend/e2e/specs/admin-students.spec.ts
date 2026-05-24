import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-students-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

function isBenign(message: string): boolean {
  return BENIGN_PATTERNS.some((re) => re.test(message));
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isBenign(msg.text())) {
      errors.push(msg.text());
    }
  });
  return errors;
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubMe(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
}

async function stubAdminAcademy(page: Page) {
  await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Academy E2E",
      timezone: "UTC",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    });
  });
}

test.describe("admin students", () => {
  test("searches, filters, and loads the next cursor using BFF-rendered attendance and dues", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests: string[] = [];
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      requests.push(url.search);
      const search = url.searchParams.get("search") ?? "";
      const status = url.searchParams.get("status") ?? "";
      const cursor = url.searchParams.get("cursor") ?? "";

      if (status === "paused") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-paused",
              full_name: "Maya Paused",
              parent_id: "parent-paused",
              parent_name: "Rina Paused",
              parent_email: "rina@example.com",
              status: "paused",
              active_session_count: 0,
              last_seen_at: null,
              attendance_rate: null,
              dues_status: "overdue",
            },
          ],
          next_cursor: null,
        });
      }

      if (search === "zara") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-zara",
              full_name: "Zara Khan",
              parent_id: "parent-zara",
              parent_name: "Aakash Khan",
              parent_email: "aakash@example.com",
              status: "active",
              active_session_count: 1,
              last_seen_at: "2026-05-12T15:00:00Z",
              attendance_rate: 0.72,
              dues_status: "due",
            },
          ],
          next_cursor: null,
        });
      }

      if (cursor === "cursor-2") {
        return fulfillJson(route, {
          students: [
            {
              student_id: "student-3",
              full_name: "Priya Shah",
              parent_id: "parent-3",
              parent_name: "Nisha Shah",
              parent_email: "nisha@example.com",
              status: "inactive",
              active_session_count: 0,
              last_seen_at: null,
              attendance_rate: null,
              dues_status: "overdue",
            },
          ],
          next_cursor: null,
        });
      }

      return fulfillJson(route, {
        students: [
          {
            student_id: "student-1",
            full_name: "Amit Rao",
            parent_id: "parent-1",
            parent_name: "Rohan Rao",
            parent_email: "rohan@example.com",
            status: "active",
            active_session_count: 2,
            last_seen_at: "2026-05-18T15:00:00Z",
            attendance_rate: 0.91,
            dues_status: "current",
          },
          {
            student_id: "student-2",
            full_name: "Leah Chen",
            parent_id: "parent-2",
            parent_name: "Min Chen",
            parent_email: "min@example.com",
            status: "active",
            active_session_count: 1,
            last_seen_at: "2026-05-17T15:00:00Z",
            attendance_rate: 0.5,
            dues_status: "due",
          },
        ],
        next_cursor: "cursor-2",
      });
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("Amit Rao");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("91%");
    await expect(page.getByTestId("admin-students-row-student-1")).toContainText("CURRENT");
    await expect(requests[0]).toContain("limit=25");

    await page.getByRole("button", { name: /^next page$/i }).click();
    await expect(page.getByTestId("admin-students-row-student-3")).toContainText("Priya Shah");
    expect(requests.some((search) => search.includes("cursor=cursor-2"))).toBe(true);

    await page.getByLabel("Search students").fill("zara");
    await expect(page.getByTestId("admin-students-row-student-zara")).toContainText("Zara Khan");
    await expect(page.getByTestId("admin-students-row-student-zara")).toContainText("72%");
    await expect(page.getByTestId("admin-students-row-student-1")).toHaveCount(0);
    expect(requests.at(-1)).toContain("search=zara");
    expect(requests.at(-1)).not.toContain("cursor=");

    await page.getByRole("button", { name: /^paused/i }).click();
    await expect(page.getByTestId("admin-students-row-student-paused")).toContainText("Maya Paused");
    expect(requests.at(-1)).toContain("status=paused");
    expect(requests.at(-1)).not.toContain("cursor=");
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("shows a truthful empty state", async ({ page }) => {
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { students: [], next_cursor: null });
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-empty")).toContainText("No students registered yet.");
  });

  test("shows a truthful error state", async ({ page }) => {
    await stubMe(page);
    await stubAdminAcademy(page);
    await page.route("**/api/v2/admin/students*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { error: { message: "boom" } }, 500);
    });

    await page.goto("/admin/students");
    await expect(page.getByTestId("admin-students-error")).toContainText("Could not load students.");
  });
});
