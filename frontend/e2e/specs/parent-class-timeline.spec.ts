/**
 * Parent class timeline (skills-first step 4): each child's own classes,
 * newest first and paged, above current level progress. A pass shows only
 * on the class that earned it; a repeated practice shows on both dates; a
 * group-only lesson never claims the child practised. Synthetic data only,
 * BFF mocked at the route layer like parent-home.spec.ts. Runs on phone and
 * desktop.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubGet(page: Page, pattern: string, body: unknown): Promise<void> {
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return json(route, body);
  });
}

const sk = (skill_id: string, name: string) => ({ skill_id, name });
const GRIP = sk("sk-grip", "Forehand grip");
const CLEAR = sk("sk-clear", "Overhead clear");
const SERVE = sk("sk-serve", "Short serve");

// Maya: Tuesday batch, then a Saturday make-up (two batches), then older.
const MAYA_PAGE_1 = {
  recaps: [
    {
      occurrence_id: "occ-sat",
      class_starts_at: "2026-11-21T16:00:00Z",
      taught_skills: [CLEAR],
      practiced_skills: [CLEAR],
      earned_skills: [CLEAR],
    },
    {
      occurrence_id: "occ-tue",
      class_starts_at: "2026-11-17T23:00:00Z",
      taught_skills: [CLEAR, GRIP],
      practiced_skills: [CLEAR],
      earned_skills: [],
    },
  ],
  next_cursor: "2026-11-17T23:00:00+00:00|occ-tue",
};
const MAYA_PAGE_2 = {
  recaps: [
    {
      occurrence_id: "occ-old",
      class_starts_at: "2026-11-10T23:00:00Z",
      taught_skills: [SERVE],
      practiced_skills: [],
      earned_skills: [],
    },
  ],
  next_cursor: null,
};
const LEO_PAGE = {
  recaps: [
    {
      occurrence_id: "occ-tue",
      class_starts_at: "2026-11-17T23:00:00Z",
      taught_skills: [CLEAR, GRIP],
      practiced_skills: [GRIP],
      earned_skills: [],
    },
  ],
  next_cursor: null,
};

function journey(studentId: string) {
  return {
    student_id: studentId,
    program_id: "prog-1",
    levels: [],
    current_level: null,
    skills: [],
    recent_wins: [],
    milestones: [],
    focus_skill_id: null,
    focus_skill_name: null,
    pathway_complete: false,
    practice_drill: null,
  };
}

async function stubFamily(page: Page): Promise<string[]> {
  const asked: string[] = [];
  await stubGet(page, "**/api/v2/me", {
    user_id: "user-parent-e2e",
    email: "parent@example.com",
    academy_id: "academy-e2e",
    roles: ["parent"],
  });
  await stubGet(page, "**/api/v2/parent/messages", { messages: [] });
  await stubGet(page, "**/api/v2/parent/academy", {
    display_name: "Aces Academy",
    timezone: "America/Chicago",
    contact_email: null,
    contact_phone: null,
    hours_text: null,
    address: null,
    logo_url: null,
  });
  await stubGet(page, "**/api/v2/parent/children", {
    children: [
      ["st-maya", "Maya Testwood"],
      ["st-leo", "Leo Testwood"],
    ].map(([student_id, full_name]) => ({
      student_id,
      full_name,
      lifecycle: "active",
      active_session_count: 1,
      attended_count: 3,
      absent_count: 0,
    })),
  });
  await page.route("**/api/v2/parent/students/*/progress-journey*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const id = /students\/([^/]+)\//.exec(route.request().url())?.[1] ?? "";
    return json(route, journey(id));
  });
  await stubGet(page, "**/api/v2/parent/students/*/certificates", { certificates: [] });
  await stubGet(page, "**/api/v2/parent/progress", { notes: [] });
  await page.route("**/api/v2/parent/students/*/class-recaps*", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const url = new URL(route.request().url());
    asked.push(url.pathname + url.search);
    // The BFF answers 404 for any child who is not this parent's.
    if (url.pathname.includes("/st-maya/")) {
      return json(route, url.searchParams.get("cursor") ? MAYA_PAGE_2 : MAYA_PAGE_1);
    }
    if (url.pathname.includes("/st-leo/")) return json(route, LEO_PAGE);
    return json(route, { error: { code: "NotFound", message: "not found", details: {} } }, 404);
  });
  return asked;
}

test.describe("parent class timeline", () => {
  test("shows each child's own classes first, with passes on the earning date", async ({
    page,
  }, testInfo) => {
    const asked = await stubFamily(page);
    await page.goto("/parent/progress?child=st-maya");

    const timeline = page.getByTestId("parent-class-recaps");
    await expect(timeline.getByRole("heading", { name: "Maya's classes" })).toBeVisible();
    // Timeline first: above the level progress.
    const journeyBox = await page.getByTestId("parent-progress-journey").boundingBox();
    const timelineBox = await timeline.boundingBox();
    expect(timelineBox!.y).toBeLessThanOrEqual(journeyBox!.y + 1);

    const items = timeline.getByTestId("parent-class-recap-item");
    await expect(items).toHaveCount(2);
    await expect(items.nth(0)).toContainText("Sat, Nov 21, 2026");
    await expect(items.nth(0)).toContainText("Passed at this class: Overhead clear");
    await expect(items.nth(1)).toContainText("Tue, Nov 17, 2026");
    await expect(items.nth(1)).not.toContainText("Passed at this class");
    // The repeated practice shows on both dates.
    await expect(timeline.getByText("Maya practised: Overhead clear")).toHaveCount(2);
    await page.screenshot({ path: testInfo.outputPath("timeline-page-1.png"), fullPage: true });

    await timeline.getByTestId("parent-class-recaps-more").click();
    await expect(items).toHaveCount(3);
    await expect(items.nth(2)).toContainText("Class lesson: Short serve");
    await expect(items.nth(2)).toContainText("did not record which skills Maya practised");
    await expect(timeline.getByTestId("parent-class-recaps-more")).toHaveCount(0);
    expect(asked).toContain(
      "/api/v2/parent/students/st-maya/class-recaps?cursor=2026-11-17T23%3A00%3A00%2B00%3A00%7Cocc-tue",
    );

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: testInfo.outputPath("timeline-older.png"), fullPage: true });
  });

  test("a sibling sees only their own practice from the same class", async ({ page }) => {
    await stubFamily(page);
    await page.goto("/parent/progress?child=st-leo");
    const timeline = page.getByTestId("parent-class-recaps");
    await expect(timeline.getByText("Leo practised: Forehand grip")).toBeVisible();
    await expect(timeline.getByText(/Overhead clear/)).toHaveCount(1); // the class lesson only
    await expect(timeline.getByText("Passed at this class")).toHaveCount(0);
  });

  test("another family's child shows no timeline", async ({ page }) => {
    const asked = await stubFamily(page);
    await page.goto("/parent/progress?child=st-other");
    await expect(page.getByTestId("parent-class-recaps")).toHaveCount(0);
    expect(asked.some((p) => p.includes("/st-maya/") || p.includes("/st-leo/"))).toBe(false);
  });
});
