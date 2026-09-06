import type { Locator } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

async function expectTouchHeight(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "element has a layout box").not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
}

test.describe("Coach Day Hub and Skill Passport", () => {
  // This journey crosses several routes; under parallel-project load the Next
  // dev server's first-compile latency can exceed the default 30s timeout.
  test.describe.configure({ mode: "serial", timeout: 90_000 });

  test("covers day hub, future date controls, skills workspace, passport, and prep link", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/dashboard");

    await expect(page.getByTestId("coach-day-hub")).toBeVisible();
    await expect(page.getByText("Coach Day Hub")).toBeVisible();
    await expect(page.getByText("Expected cut")).toHaveCount(0);
    await expect(page.getByText("Backhand clear")).toBeVisible();

    await page.getByRole("button", { name: "Tomorrow" }).click();
    await expect(page.getByText("Junior A")).toBeVisible();
    await page.getByRole("button", { name: "Today" }).click();

    await Promise.all([
      page.waitForURL(/\/coach\/sessions\/occ-today-1\?date=\d{4}-\d{2}-\d{2}$/),
      page.getByRole("link", { name: "Open session" }).click(),
    ]);
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await Promise.all([
      page.waitForURL(/\/coach\/students\/st1\/passport\?/),
      page.getByTestId("roster-st1").getByRole("link", { name: "Skills" }).click(),
    ]);
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();

    await page.goto("/coach/dashboard", { waitUntil: "domcontentloaded" });
    await expect(page.getByTestId("coach-day-hub")).toBeVisible();

    const skillUpdatesLink = page.getByRole("link", { name: "Open skill updates" });
    await Promise.all([
      page.waitForURL(/\/coach\/sessions\/occ-today-1\/skills\?date=\d{4}-\d{2}-\d{2}$/),
      skillUpdatesLink.click(),
    ]);
    await expect(page.getByTestId("coach-session-skills")).toBeVisible();
    await expect(page.getByRole("button", { name: "By skill" })).toBeVisible();
    await page.getByRole("button", { name: "Update selected students" }).click();
    await expect.poll(() => mock.bulkSkillCalls.length).toBe(1);

    await page.getByRole("button", { name: "By student" }).click();
    await expect(page.getByLabel("Student")).toBeVisible();
    await expect(page.getByText("Backhand clear")).toBeVisible();
    await page.getByRole("button", { name: "Save" }).first().click();
    await expect
      .poll(() => mock.skillStatusCalls.length, {
        message: "wait for the skill status mutation to settle before leaving",
      })
      .toBe(1);

    await page.goto("/coach/dashboard");
    await expect(page.getByTestId("coach-day-hub")).toBeVisible();
    // Dead placeholder actions must not ship: no coach-scoped messaging or
    // absence workflow exists yet, so these buttons were removed.
    await expect(page.getByRole("button", { name: "Message parents" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "I can't attend" })).toHaveCount(0);

    await Promise.all([
      page.waitForURL(/\/coach\/today\/plan\?date=\d{4}-\d{2}-\d{2}$/),
      page.getByRole("link", { name: "Prepare" }).click(),
    ]);
    await expect(page.getByTestId("coach-teaching-plan")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Lesson 3: Overhead Clear" })).toBeVisible();
  });

  test("passport skill cards use phone-sized controls, share skill notes, and never overflow", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/students/st1/passport?student_name=Alice");
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    const card = page.getByTestId("passport-skill-skill-backhand");
    await expect(card).toBeVisible();
    await expectTouchHeight(card.getByLabel("Status for Backhand clear"));
    await expectTouchHeight(card.getByRole("button", { name: "Record Test" }));
    await expectTouchHeight(card.getByRole("button", { name: "Notes" }));
    await card.getByRole("button", { name: "Record Test" }).click();
    await expectTouchHeight(card.getByRole("button", { name: "Save Test" }));

    const noOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noOverflow).toBe(true);

    // Skill notes: share switch is off by default, Add Note is 44px, the
    // saved note lists with its audience and the toggle PATCHes it back.
    await card.getByRole("button", { name: "Notes" }).click();
    const share = page.getByTestId("skill-note-share");
    await expect(share).not.toBeChecked();
    // The copy must not promise a parent surface that does not exist yet.
    await expect(page.getByTestId("skill-note-share-hint")).toHaveText(
      /not in the parent portal yet/i,
    );
    await share.check();
    await page.getByPlaceholder("Add a note about this skill...").fill("Shuttle contact is higher");
    const addButton = page.getByRole("button", { name: "Add Note" });
    await expectTouchHeight(addButton);
    await addButton.click();
    await expect.poll(() => mock.skillNoteCalls.length).toBe(1);
    expect(mock.skillNoteCalls[0]).toEqual({
      skill_id: "skill-backhand",
      body: "Shuttle contact is higher",
      visibility: "shared",
    });
    await expect(page.getByTestId("skill-note-visibility-skill-note-1")).toHaveText(/^Shared$/);
    const toggle = page.getByTestId("skill-note-share-toggle-skill-note-1");
    await expectTouchHeight(toggle);
    await toggle.click();
    await expect.poll(() => mock.skillNoteVisibilityCalls.length).toBe(1);
    expect(mock.skillNoteVisibilityCalls[0]).toEqual({
      note_id: "skill-note-1",
      visibility: "private",
    });
    await expect(page.getByTestId("skill-note-visibility-skill-note-1")).toHaveText(/private/i);
  });

  test("the share toggle only appears on notes this coach wrote", async ({ page, mock }) => {
    // ListSkillNotes has no author filter, but SetSkillNoteVisibility 404s a
    // non-supervisor who did not write the note — so a toggle on a colleague's
    // note could never succeed and must not be offered.
    const created_at = new Date().toISOString();
    mock.skillNotes.push(
      {
        note_id: "skill-note-mine",
        academy_id: "academy-e2e",
        student_id: "st1",
        skill_id: "skill-backhand",
        coach_id: "user-coach-e2e",
        session_id: null,
        body: "My own note",
        created_at,
        visibility: "private",
      },
      {
        note_id: "skill-note-theirs",
        academy_id: "academy-e2e",
        student_id: "st1",
        skill_id: "skill-backhand",
        coach_id: "user-other-coach",
        session_id: null,
        body: "A colleague's note",
        created_at,
        visibility: "private",
      },
    );

    await page.goto("/coach/students/st1/passport?student_name=Alice");
    await expect(page.getByTestId("coach-student-passport")).toBeVisible();
    await page
      .getByTestId("passport-skill-skill-backhand")
      .getByRole("button", { name: "Notes" })
      .click();

    // Both notes list; only the viewer's own carries a toggle.
    await expect(page.getByTestId("skill-note-skill-note-theirs")).toContainText(
      "A colleague's note",
    );
    await expect(page.getByTestId("skill-note-share-toggle-skill-note-mine")).toBeVisible();
    await expect(page.getByTestId("skill-note-share-toggle-skill-note-theirs")).toHaveCount(0);
  });
});
