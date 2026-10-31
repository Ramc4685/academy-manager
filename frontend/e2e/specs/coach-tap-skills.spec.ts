/**
 * Mobile smoke spec for the coach "Got it" tap mode on the session Skills tab.
 *
 * Runs against the route-layer BFF mock (`e2e/fixtures/mock-api.ts`): the
 * skill board stub has one level with "Backhand clear" still LEARNING for both
 * roster students. Tapping a student posts one mastered call for that student.
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
});
