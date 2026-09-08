/**
 * Mobile smoke spec for the coach session skill board.
 *
 * Runs against the route-layer BFF mock (`e2e/fixtures/mock-api.ts`, which
 * also bypasses Firebase auth): the board endpoint is stubbed with one level,
 * two skills and both roster students placed. Below `md:` the board renders
 * as cards (`skill-card-<studentId>`) with 44px skill chips; the cell editor
 * opens as a bottom sheet. The backend contract is covered by
 * backend/v2/tests/interface/test_coach_skill_routes.py.
 */

import type { Locator } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

async function expectTouchHeight(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "element has a layout box").not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
}

test.describe("coach skill board (mobile)", () => {
  test("by-student cards have 44px chips, open the cell editor, and never overflow", async ({
    page,
    mock,
  }) => {
    void mock;
    await page.goto("/coach/sessions/s-today-1/progress");
    await expect(page.getByTestId("skill-board")).toBeVisible();
    await expect(page.getByTestId("skill-board-level-1")).toBeVisible();

    const card = page.getByTestId("skill-card-st1");
    await expect(card).toContainText("Alice");
    const chips = card.getByRole("button");
    await expect(chips).toHaveCount(2);
    await expectTouchHeight(chips.nth(0));
    await expectTouchHeight(chips.nth(1));

    const noOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noOverflow).toBe(true);

    await chips.nth(0).click();
    const editor = page.getByTestId("skill-cell-editor");
    await expect(editor).toBeVisible();
    await expect(editor).toContainText("Backhand clear");
    await expectTouchHeight(page.getByTestId("quick-pass"));
    const editorBox = await editor.boundingBox();
    const viewport = page.viewportSize();
    expect(editorBox).not.toBeNull();
    expect(viewport).not.toBeNull();
    expect(editorBox!.x).toBeGreaterThanOrEqual(0);
    expect(editorBox!.x + editorBox!.width).toBeLessThanOrEqual(viewport!.width + 1);
    await page.getByRole("button", { name: "Close" }).click();
    await expect(editor).toHaveCount(0);
  });

  test("by-skill mode lists students and opens the cell editor", async ({ page, mock }) => {
    void mock;
    await page.goto("/coach/sessions/s-today-1/progress");
    await expect(page.getByTestId("skill-board")).toBeVisible();

    await page.getByRole("button", { name: "By skill" }).click();
    const row = page.getByTestId("by-skill-student-st2");
    await expectTouchHeight(row);
    await row.click();
    await expect(page.getByTestId("skill-cell-editor")).toBeVisible();
    await expect(page.getByTestId("quick-pass")).toBeVisible();
  });
});
