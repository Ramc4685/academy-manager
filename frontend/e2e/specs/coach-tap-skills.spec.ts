/**
 * Mobile smoke spec for the coach "Got it" tap mode on the session Skills tab.
 *
 * Runs against the route-layer BFF mock (`e2e/fixtures/mock-api.ts`): the
 * skill board stub has one level with "Backhand clear" still LEARNING for both
 * roster students. Tapping a student posts one mastered call for that student;
 * the coach can then add a one-line note for that student's parents.
 * The backend contract is covered by test_coach_skill_routes.py and
 * test_tap_to_master_real_mongo.py.
 */

import { test, expect } from "../fixtures/mock-api";

test.describe("coach tap-to-master (mobile)", () => {
  test("opens on Got it, taps one student, and keeps rows touch-sized", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1/skills");
    const workspace = page.getByTestId("coach-tap-skills");
    await expect(workspace).toBeVisible();
    await expect(workspace).toContainText("Who got “Backhand clear”?");

    const row = workspace.getByRole("button", { name: /Alice/ });
    const box = await row.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(44);

    await row.click();
    await expect.poll(() => mock.masteredCalls.length).toBe(1);
    expect(mock.masteredCalls[0].method).toBe("POST");
    expect(mock.masteredCalls[0].url).toContain("/skills/skill-backhand/mastered");
    expect(mock.masteredCalls[0].body).toMatchObject({
      program_id: "prog-001",
      student_ids: ["st1"],
    });

    const noOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noOverflow).toBe(true);
  });

  test("adds a note for the parents after the tap", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1/skills");
    const workspace = page.getByTestId("coach-tap-skills");
    await workspace.getByRole("button", { name: /Alice/ }).click();

    await workspace.getByRole("button", { name: /\+ Note for Alice/ }).click();
    await workspace.getByLabel(/One line for Alice/).fill("Much quicker to the net this week.");
    await workspace.getByRole("button", { name: "Save note" }).click();

    await expect(workspace).toContainText("“Much quicker to the net this week.”");
    const put = mock.masteredCalls.find((c) => c.method === "PUT");
    expect(put!.url).toContain("/students/st1/skills/skill-backhand/mastered/note");
    expect(put!.body).toEqual({ note: "Much quicker to the net this week." });
    await expect(workspace.getByRole("button", { name: /Edit the note for Alice/ })).toBeVisible();
    await workspace.screenshot({ path: "test-results/coach-tap-note.png" });
  });
});
