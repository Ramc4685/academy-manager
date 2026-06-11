/**
 * Mobile smoke spec for the coach session skill board.
 *
 * SKIPPED: The project's e2e suite has no seeded-auth path for coach pages.
 * The existing fixture (`frontend/e2e/fixtures/mock-api.ts`) stubs network at
 * the Playwright route layer and patches `__fakeFirebaseUser` via initScript,
 * but it does not provide:
 *   - A real (or seeded-fake) Firebase ID token that the Next.js middleware
 *     accepts for coach routes.
 *   - A known seeded session ID with a placed roster for asserting board data.
 *
 * To un-skip this spec you need:
 *   1. A `storageState` or token-injection helper that authenticates a coach
 *      user against the local Firebase emulator (or a test-only bypass in the
 *      Next.js middleware).
 *   2. The local stack seeded with `seed_badminton_pathway` and at least one
 *      session whose roster has students placed in a level
 *      (see `scripts/local_test_stack.sh`).
 *   3. Replace `SESSION_ID_FROM_SEED` below with the actual session ID
 *      produced by that seed.
 *
 * The backend contract is fully covered by interface tests:
 *   backend/v2/tests/interface/test_coach_skill_routes.py
 *   backend/v2/tests/interface/test_admin_skill_board.py
 */

import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 } });

test.describe("coach skill board (mobile)", () => {
  test.skip(
    true,
    "Requires seeded local stack + coach auth helper — see file comment for prerequisites",
  );

  test("by-skill mode renders and opens the cell editor", async ({ page }) => {
    // Prerequisite: local stack running with seed_badminton_pathway applied,
    // coach authenticated, and SESSION_ID_FROM_SEED replaced with a real ID.
    await page.goto("/coach/sessions/SESSION_ID_FROM_SEED/progress");
    await expect(page.getByTestId("skill-board")).toBeVisible();

    await page.getByRole("button", { name: "By skill" }).click();
    await page.getByTestId(/by-skill-student-/).first().click();
    await expect(page.getByTestId("skill-cell-editor")).toBeVisible();
    await expect(page.getByTestId("quick-pass")).toBeVisible();
  });
});
