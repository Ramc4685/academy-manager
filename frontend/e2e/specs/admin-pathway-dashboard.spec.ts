import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Progress → owner skill-pathway dashboard against a mocked admin BFF: the
 * almost-there and stuck lists render, and switching the level-up rule
 * writes requires_admin_approval on every level of the program.
 */

const ADMIN_ME = {
  user_id: "user-admin-dash-e2e",
  email: "owner@riverside.example",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const WEEK = 7 * 24 * 60 * 60 * 1000;

const LEVELS = [
  ["Grip & Control", 14],
  ["Net & Movement", 11],
  ["Serve & Lift", 9],
  ["Midcourt Speed", 6],
  ["Rearcourt Shots", 4],
  ["Match & Tactics", 2],
] as const;

function dashboard(rule: string) {
  return {
    program_id: "prog-1",
    program_name: "Badminton Pathway",
    skills_mastered_this_week: 24,
    level_ups_this_month: 5,
    levels: LEVELS.map(([name, count], i) => ({
      level_id: `lvl-${i + 1}`,
      name,
      sequence: i + 1,
      player_count: count,
      requires_admin_approval: rule === "approve_first",
    })),
    level_up_rule: rule,
    almost_there: [
      { student_id: "st-z", student_name: "Zara", level_name: "Net & Movement", level_sequence: 2, missing_skill_name: "Net rally" },
      { student_id: "st-a", student_name: "Aarav", level_name: "Grip & Control", level_sequence: 1, missing_skill_name: "Basic rally" },
    ],
    stuck: [
      {
        student_id: "st-e",
        student_name: "Ethan",
        level_name: "Net & Movement",
        level_sequence: 2,
        skills_passed: 2,
        skills_total: 6,
        last_win_at: new Date(Date.now() - 7 * WEEK).toISOString(),
        level_started_at: new Date(Date.now() - 12 * WEEK).toISOString(),
      },
      {
        student_id: "st-r",
        student_name: "Ria",
        level_name: "Grip & Control",
        level_sequence: 1,
        skills_passed: 0,
        skills_total: 6,
        last_win_at: null,
        level_started_at: new Date(Date.now() - 8 * WEEK).toISOString(),
      },
    ],
    unplaced_count: 3,
    coaches: [
      { coach_id: "c-a", coach_name: "Coach Asha", skills_ticked: 18 },
      { coach_id: "c-b", coach_name: "Coach Ben", skills_ticked: 6 },
      { coach_id: "c-c", coach_name: "Coach Cara", skills_ticked: 0 },
    ],
  };
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stub(page: Page): Promise<string[]> {
  const puts: string[] = [];
  let rule = "automatic";
  await page.route("**/api/v2/admin/**", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, {}) : route.fallback(),
  );
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, ADMIN_ME) : route.fallback(),
  );
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Riverside Shuttle Club",
          academy_slug: "academy-e2e",
          roles: ADMIN_ME.roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/pathway/dashboard", (route) =>
    fulfillJson(route, dashboard(rule)),
  );
  await page.route("**/api/v2/admin/levels/*", (route) => {
    const request = route.request();
    if (request.method() !== "PUT") return route.fallback();
    const body = request.postDataJSON() as { requires_admin_approval: boolean };
    puts.push(`${request.url().split("/").pop()}=${body.requires_admin_approval}`);
    if (puts.length === LEVELS.length) rule = "approve_first";
    return fulfillJson(route, {});
  });
  return puts;
}

test.describe("admin pathway dashboard", () => {
  test("shows who is almost there and who is stuck, and sets the level-up rule", async ({
    page,
  }) => {
    const puts = await stub(page);
    await page.goto("/admin/pathway/dashboard");

    const almost = page.getByTestId("pathway-almost-there");
    await expect(almost).toContainText("Zara");
    await expect(almost).toContainText("Level 2 · needs Net rally");
    const stuck = page.getByTestId("pathway-stuck");
    await expect(stuck).toContainText("Level 2 · 2 of 6 skills · last win 7 weeks ago");
    await expect(stuck).toContainText("no win yet");
    await expect(page.getByTestId("pathway-coaches")).toContainText("Coach Cara");
    await page.screenshot({ path: "test-results/pathway-dashboard-phone.png", fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({ path: "test-results/pathway-dashboard-desktop.png", fullPage: true });

    const approveFirst = page.getByRole("radio", { name: /I approve first/ });
    await expect(page.getByRole("radio", { name: /Automatic/ })).toBeChecked();
    await approveFirst.check();

    await expect.poll(() => puts.length).toBe(LEVELS.length);
    expect(puts.every((p) => p.endsWith("=true"))).toBe(true);
    await expect(approveFirst).toBeChecked();
  });
});
