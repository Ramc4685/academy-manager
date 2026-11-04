/**
 * Phase 3 E2E: coach daily teaching plan (mobile).
 *
 * Mirrors the mock-API fixture pattern from coach-today.spec.ts — network is
 * stubbed at the Playwright route layer (no real backend; the backend contract
 * is covered by backend/v2/tests/interface/test_coach_teaching_plan.py).
 *
 * Asserts: the plan renders (lesson card first, then students grouped by
 * level); "Passed" issues the quick-pass test POST (success_count 1);
 * "Needs review" issues the status POST; YouTube hrefs are correct; the PDF
 * citation chip is non-interactive text; error → retry recovers.
 *
 * #895: the one-tap buttons speak the same seven-state vocabulary as the
 * skills page, the passport and the skill board — "Passed", never "Mastered" —
 * they publish the student's current state through `aria-pressed`, and a
 * status write can be undone from the row.
 */

import { test, expect } from "../fixtures/mock-api";

test.describe("Coach teaching plan", () => {
  test("renders the plan with lesson card and students", async ({
    page,
    mock,
  }) => {
    void mock;
    await page.goto("/coach/today/plan");

    await expect(page.getByTestId("coach-teaching-plan")).toBeVisible();
    await expect(page.getByTestId("plan-session-s-today-1")).toContainText(
      "Junior A",
    );

    // Lesson card renders before student rows.
    const card = page.getByTestId("lesson-card-card-3");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Overhead Clear");
    await expect(card).toContainText("Teaching points");

    await expect(page.getByTestId("student-focus-st1")).toContainText("Alice");
    await expect(page.getByTestId("student-focus-st1")).toContainText(
      "Forehand Clear",
    );
    // NEEDS_REVIEW student is highlighted as Review.
    await expect(page.getByTestId("student-focus-st2")).toContainText("Review");
  });

  test("Passed issues a quick-pass test POST (success_count 1)", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/today/plan");
    await expect(page.getByTestId("student-focus-st1")).toBeVisible();

    const passed = page.getByTestId("outcome-st1-passed");
    // #895: the button speaks the shared vocabulary, not "Mastered".
    await expect(passed).toHaveText("Passed");
    await passed.click();

    await expect.poll(() => mock.testCalls.length).toBe(1);
    expect(mock.testCalls[0]).toMatchObject({
      studentId: "st1",
      skillId: "sk-1",
      body: {
        attempts_count: 1,
        success_count: 1,
        program_id: "prog-badminton",
        level_id: "lvl-1",
        session_id: "s-today-1",
      },
    });
    // No status write — Passed must go through the test endpoint only.
    expect(mock.statusCalls.length).toBe(0);
    await expect(page.getByTestId("outcome-done-st1")).toContainText("Passed");
    // Passed has no server-side revert (CoachSettableStatus rejects PASSED),
    // so the row must NOT offer an Undo it cannot honour.
    await expect(page.getByTestId("outcome-undo-st1")).toHaveCount(0);
  });

  test("the current skill state reads as pressed on the one-tap buttons", async ({
    page,
    mock,
  }) => {
    void mock;
    await page.goto("/coach/today/plan");
    await expect(page.getByTestId("student-focus-st1")).toBeVisible();

    // Alice's next skill is PRACTICING; Bob's is NEEDS_REVIEW.
    await expect(page.getByTestId("outcome-st1-practicing")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("outcome-st1-introduced")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(page.getByTestId("outcome-st1-passed")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(page.getByTestId("outcome-st2-needs-review")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("Undo re-sends the status the skill had before the tap", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/today/plan");
    await expect(page.getByTestId("student-focus-st1")).toBeVisible();

    // st1 is PRACTICING; move it to INTRODUCED, then undo.
    await page.getByTestId("outcome-st1-introduced").click();
    await expect.poll(() => mock.statusCalls.length).toBe(1);
    expect(mock.statusCalls[0]?.body).toMatchObject({ status: "INTRODUCED" });

    const undo = page.getByTestId("outcome-undo-st1");
    await expect(undo).toBeVisible();
    await undo.click();

    await expect.poll(() => mock.statusCalls.length).toBe(2);
    expect(mock.statusCalls[1]).toMatchObject({
      studentId: "st1",
      skillId: "sk-1",
      body: {
        status: "PRACTICING",
        level_id: "lvl-1",
        program_id: "prog-badminton",
      },
    });
    // The test endpoint is never touched by an undo.
    expect(mock.testCalls.length).toBe(0);
    await expect(undo).toHaveCount(0);
  });

  test("Needs review issues the status POST", async ({ page, mock }) => {
    await page.goto("/coach/today/plan");
    await expect(page.getByTestId("student-focus-st1")).toBeVisible();

    await page.getByTestId("outcome-st1-needs-review").click();

    await expect.poll(() => mock.statusCalls.length).toBe(1);
    expect(mock.statusCalls[0]).toMatchObject({
      studentId: "st1",
      skillId: "sk-1",
      body: {
        status: "NEEDS_REVIEW",
        level_id: "lvl-1",
        program_id: "prog-badminton",
      },
    });
    expect(mock.testCalls.length).toBe(0);
    await expect(page.getByTestId("outcome-done-st1")).toBeVisible();
  });

  test("YouTube links carry the correct href", async ({ page, mock }) => {
    void mock;
    await page.goto("/coach/today/plan");
    await expect(page.getByTestId("lesson-card-card-3")).toBeVisible();

    const cardVideo = page.getByTestId("lesson-card-youtube-card-3-0");
    await expect(cardVideo).toHaveAttribute("href", "https://youtu.be/clear-demo");
    await expect(cardVideo).toHaveAttribute("target", "_blank");
    await expect(cardVideo).toHaveAttribute("rel", "noopener noreferrer");

    const skillVideo = page.getByTestId("student-youtube-st1");
    await expect(skillVideo).toHaveAttribute("href", "https://youtu.be/fh-clear");
  });

  test("PDF citation chip is non-interactive text, not a link", async ({
    page,
    mock,
  }) => {
    void mock;
    await page.goto("/coach/today/plan");

    const pdf = page.getByTestId("lesson-card-pdf-card-3-0");
    await expect(pdf).toBeVisible();
    await expect(pdf).toContainText("Shuttle Time · Starter Lessons");
    // Rendered as a <span>, never an anchor.
    expect(await pdf.evaluate((el) => el.tagName)).toBe("SPAN");
    await expect(
      page.getByRole("link", { name: /Shuttle Time/ }),
    ).toHaveCount(0);
  });

  test("error then retry recovers", async ({ page, mock }) => {
    mock.failTeachingPlan = true;
    await page.goto("/coach/today/plan");

    // The app retries 5xx up to 3× with backoff, so allow time for the query
    // to exhaust retries before the error banner renders.
    const alert = page.getByTestId("plan-error");
    await expect(alert).toContainText("Couldn't load the teaching plan", {
      timeout: 15000,
    });

    // Recover the backend, then retry.
    mock.failTeachingPlan = false;
    await alert.getByRole("button", { name: "Retry" }).click();

    await expect(page.getByTestId("lesson-card-card-3")).toBeVisible();
    await expect(page.getByTestId("student-focus-st1")).toContainText("Alice");
  });
});
