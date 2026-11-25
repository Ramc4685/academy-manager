/**
 * Coach teaching rotation (skills-first step 5): the plan gives each level
 * group a drill picked from this batch's delivery history, says why, and
 * flags a repeat, variations and a warm-up from the level below; the class
 * recap records what each group worked on. Synthetic names, BFF stubbed at
 * the route layer. Runs on phone and desktop.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Route } from "@playwright/test";

const card = (card_id: string, title: string, point: string) => ({
  card_id,
  lesson_number: 1,
  title,
  goal_summary: "",
  teaching_points: [point],
  equipment: [],
  activity_summary: "",
  safety_notes: [],
  source: "BWF_SHUTTLE_TIME",
  module_name: "Starter Lessons",
  lesson_range: "1-2",
  page_hint: null,
  resource_links: [],
});
const next = (skill_id: string, name: string, level_id: string) => ({
  skill_id,
  name,
  sequence: 1,
  level_id,
  status: "PRACTICING",
  is_review: false,
  criteria: [],
  youtube_links: [],
});
const GRIP = card("c-grip", "Grip ladders", "Thumb behind the handle");
const CLEAR = card("c-clear", "Clear to the back", "Turn side-on early");

function plan(base: { start_at: string | null; end_at: string | null }) {
  return {
    date: new Date().toISOString().slice(0, 10),
    program_id: "prog-badminton",
    program_name: "Badminton",
    pathway_configured: true,
    sessions: [
      {
        session_id: "s-today-1",
        occurrence_id: "occ-today-1",
        title: "Junior A",
        location: "Court 1",
        ...base,
        unplaced: [],
        groups: [
          {
            level_id: "lvl-1",
            level_name: "Starter",
            level_sequence: 1,
            youtube_links: [],
            lesson_card: GRIP,
            history_known: false,
            students: [
              {
                student_id: "st1",
                student_name: "Alice Testwood",
                focus: "practice",
                next_skill: next("sk-grip", "Forehand grip", "lvl-1"),
              },
            ],
            assignment: {
              card: GRIP,
              cue: "Thumb behind the handle",
              need_count: 1,
              last_taught_at: null,
              is_repeat: false,
              variations: [],
            },
            reinforcement: null,
          },
          {
            level_id: "lvl-2",
            level_name: "Rallying",
            level_sequence: 2,
            youtube_links: [],
            lesson_card: CLEAR,
            history_known: true,
            students: [
              {
                student_id: "st3",
                student_name: "Cy Testwood",
                focus: "practice",
                next_skill: next("sk-clear", "Overhead clear", "lvl-2"),
              },
              {
                student_id: "st4",
                student_name: "Di Testwood",
                focus: "practice",
                next_skill: next("sk-drop", "Drop shot", "lvl-2"),
              },
            ],
            assignment: {
              card: CLEAR,
              cue: "Turn side-on early",
              need_count: 1,
              last_taught_at: "2026-11-17T23:00:00Z",
              is_repeat: true,
              variations: [
                {
                  student_id: "st4",
                  student_name: "Di Testwood",
                  skill_id: "sk-drop",
                  skill_name: "Drop shot",
                },
              ],
            },
            reinforcement: {
              card: GRIP,
              cue: null,
              need_count: 0,
              last_taught_at: null,
              is_repeat: false,
              variations: [],
            },
          },
        ],
      },
    ],
  };
}

const skill = (skill_id: string, name: string, level_name: string) => ({
  skill_id,
  name,
  level_name,
});

function recap(groupLessons: { level_id: string; skill_ids: string[] }[]) {
  return {
    occurrence_id: "occ-today-1",
    class_starts_at: new Date().toISOString(),
    can_edit: true,
    can_resolve: false,
    ai_enabled: false,
    revision: 1,
    source: "direct",
    updated_at: null,
    taught_skills: [
      skill("sk-grip", "Forehand grip", "Starter"),
      skill("sk-clear", "Overhead clear", "Rallying"),
    ],
    practice: [],
    passes: [],
    roster: [
      { student_id: "st1", name: "Alice Testwood", attendance: "present" },
      { student_id: "st3", name: "Cy Testwood", attendance: "present" },
    ],
    skill_options: [],
    reports: [],
    groups: [
      { level_id: "lvl-1", name: "Starter", student_ids: ["st1"] },
      { level_id: "lvl-2", name: "Rallying", student_ids: ["st3"] },
    ],
    group_lessons: groupLessons,
  };
}

test.describe("Coach teaching rotation", () => {
  test("each group's drill says who it is for, when it was last done, and what else", async ({
    page,
    mock,
  }) => {
    const first = mock.teachingPlan.sessions[0];
    mock.teachingPlan = plan({ start_at: first.start_at, end_at: first.end_at }) as never;
    await page.goto("/coach/today/plan");

    const beginners = page.getByTestId("plan-assignment-1");
    await expect(beginners).toContainText("Cue: Thumb behind the handle");
    await expect(beginners).toContainText("For 1 of 1 child.");
    await expect(beginners).toContainText("No delivery history yet for this group.");
    await expect(page.getByTestId("plan-repeat-1")).toHaveCount(0);

    const rallying = page.getByTestId("plan-assignment-2");
    await expect(rallying).toContainText("For 1 of 2 children.");
    await expect(rallying).toContainText("Last worked on Tue, Nov 17.");
    await expect(page.getByTestId("plan-repeat-2")).toBeVisible();
    await expect(page.getByTestId("plan-variations-2")).toContainText(
      "Di Testwood: Drop shot",
    );
    await expect(page.getByTestId("plan-reinforcement-2")).toContainText(
      "Warm-up from the level below: Grip ladders",
    );
    // The assignment's card is the one shown.
    await expect(page.getByTestId("lesson-card-c-clear")).toBeVisible();
  });

  test("the recap records what each group worked on for the next plan", async ({
    page,
    mock,
  }) => {
    void mock;
    const saves: unknown[] = [];
    await page.route("**/api/v2/coach/occurrences/occ-today-1/class-recap", async (route: Route) => {
      const method = route.request().method();
      if (method === "PUT") {
        const body = route.request().postDataJSON();
        saves.push(body);
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...recap(body.group_lessons), revision: 2 }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(recap([{ level_id: "lvl-1", skill_ids: ["sk-grip"] }])),
      });
    });
    await page.goto("/coach/sessions/occ-today-1?recap=open");

    const groups = page.getByTestId("recap-groups");
    await expect(groups).toContainText("What each group worked on");
    await expect(page.getByTestId("recap-group-lvl-1")).toContainText("Alice Testwood");
    await expect(page.getByTestId("group-lvl-1-sk-grip")).toHaveAttribute("aria-pressed", "true");
    const clear = page.getByTestId("group-lvl-2-sk-clear");
    await expect(clear).toHaveAttribute("aria-pressed", "false");
    await clear.click();
    await page.getByTestId("recap-save").click();

    await expect.poll(() => saves.length).toBe(1);
    expect((saves[0] as { group_lessons: unknown }).group_lessons).toEqual([
      { level_id: "lvl-1", skill_ids: ["sk-grip"] },
      { level_id: "lvl-2", skill_ids: ["sk-clear"] },
    ]);
    await expect(page.getByTestId("group-lvl-2-sk-clear")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
  test("a reported pass is added to the recap and saved through the pass rules", async ({
    page,
    mock,
  }) => {
    void mock;
    const saves: { passes?: unknown }[] = [];
    const reported = {
      ...recap([]),
      reports: [
        {
          report_id: "r-1",
          is_mine: true,
          text: "Cy passed his overhead clear today.",
          submitted_at: new Date().toISOString(),
          outcome: "applied",
          ai_used: true,
          questions: [],
          pass_claims: [{ student_id: "st3", skill_id: "sk-clear" }],
          applied_revision: 1,
          resolved_at: null,
        },
      ],
    };
    await page.route("**/api/v2/coach/occurrences/occ-today-1/class-recap", async (route: Route) => {
      if (route.request().method() === "PUT") {
        saves.push(route.request().postDataJSON());
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...reported,
            revision: 2,
            passes: [
              { student_id: "st3", skill_id: "sk-clear", receipt: "recorded", added_revision: 2 },
            ],
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(reported),
      });
    });
    await page.goto("/coach/sessions/occ-today-1?recap=open");

    await expect(page.getByTestId("recap-pass-claims")).toContainText(
      "Cy Testwood passed Overhead clear",
    );
    await page.getByTestId("recap-claim-add-st3-sk-clear").click();
    await expect(page.getByTestId("pass-st3-sk-clear")).toHaveAttribute("aria-pressed", "true");
    await page.getByTestId("recap-save").click();

    await expect.poll(() => saves.length).toBe(1);
    expect(saves[0].passes).toEqual([{ student_id: "st3", skill_id: "sk-clear" }]);
    await expect(page.getByTestId("recap-claim-add-st3-sk-clear")).toHaveCount(0);
  });
});
