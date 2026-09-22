/**
 * Issue #846: "Mark rest present" holds its batch for a few seconds so the
 * coach can undo it.
 *
 * The bar is a DELAYED SAVE, not a compensating one. Inside the window
 * nothing has been sent — no bulk POST online, no IndexedDB queue entry
 * offline — so Undo costs the parent nothing: no notification, no billing
 * sync. Every other way out of the window commits the batch, because losing
 * a coach's marks is worse than sending one they meant to cancel.
 */

import { test, expect } from "../fixtures/mock-api";

// The window is 5s (lib/coach/bulk-mark-undo.ts), so anything that waits it
// out needs more than Playwright's 5s default.
const PAST_WINDOW = { timeout: 15_000 };

test.describe("Coach mark-rest-present undo window", () => {
  test.slow();

  test("nothing is sent while the window is open, then the batch goes out", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");

    const bulkButton = page.getByTestId("mark-all-present");
    await expect(bulkButton).toContainText("Mark rest present (2)");
    await bulkButton.click();

    // The bar answers in the thumb arc, and the rows say "held", not "saved".
    const undoBar = page.getByTestId("mark-all-undo-bar");
    await expect(undoBar).toContainText("Marked 2 present");
    await expect(page.getByTestId("mark-all-undo")).toBeVisible();
    await expect(page.getByTestId("roster-st1")).toHaveAttribute("data-mark-pending", "true");
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    // The tap itself reaches nothing.
    await page.waitForTimeout(1_000);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
    expect(mock.attendanceCalls).toHaveLength(0);

    await expect.poll(() => mock.bulkAttendanceCalls.length, PAST_WINDOW).toBe(1);
    expect(mock.bulkAttendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      entries: [
        { student_id: "st1", status: "present" },
        { student_id: "st2", status: "present" },
      ],
    });
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("roster-st1")).not.toHaveAttribute(
      "data-mark-pending",
      "true",
    );
    await expect(undoBar).toHaveCount(0);
    await expect(bulkButton).toContainText("All marked");
  });

  test("Undo inside the window means the marks never reach the server", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");

    await page.getByTestId("mark-all-present").click();
    await expect(page.getByTestId("mark-all-undo-bar")).toBeVisible();
    await page.getByTestId("mark-all-undo").click();

    await expect(page.getByTestId("mark-all-undo-bar")).toHaveCount(0);
    await expect(page.getByTestId("mark-all-present")).toContainText("Mark rest present (2)");
    await expect(page.getByTestId("roster-st1")).not.toHaveAttribute(
      "data-mark-pending",
      "true",
    );

    // Well past the window: the cancelled batch is gone, not merely delayed.
    await page.waitForTimeout(7_000);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
    expect(mock.attendanceCalls).toHaveLength(0);
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  test("backgrounding the phone inside the window sends the batch at once", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");

    await page.getByTestId("mark-all-present").click();
    await expect(page.getByTestId("mark-all-undo-bar")).toBeVisible();

    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        value: "hidden",
        configurable: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // 3s < the 5s window: this call can only be the flush, not the timer.
    await expect.poll(() => mock.bulkAttendanceCalls.length, { timeout: 3_000 }).toBe(1);
  });

  test("leaving the page inside the window sends the batch at once", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");

    await page.getByTestId("mark-all-present").click();
    await expect(page.getByTestId("mark-all-undo-bar")).toBeVisible();

    // iOS Safari backgrounds a PWA with pagehide and not always with
    // visibilitychange, so the page listens for both.
    await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));

    await expect.poll(() => mock.bulkAttendanceCalls.length, { timeout: 3_000 }).toBe(1);
  });

  test("offline, the queue is written only after the window closes", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-indicator")).toBeVisible();

    await page.getByTestId("mark-all-present").click();
    await expect(page.getByTestId("mark-all-undo-bar")).toContainText("Marked 2 present");

    // An undone batch must leave nothing on the phone either: no QUEUED tag
    // while the window is open.
    await page.waitForTimeout(1_000);
    await expect(page.getByTestId("mark-queued-st1")).toHaveCount(0);

    await expect(page.getByTestId("mark-queued-st1")).toBeVisible(PAST_WINDOW);
    await expect(page.getByTestId("mark-queued-st2")).toBeVisible();
    await expect(page.getByTestId("queued-count")).toContainText("2 queued");
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
    expect(mock.attendanceCalls).toHaveLength(0);

    // Reconnecting replays them one by one over the single-mark endpoint,
    // exactly as an offline tap-by-tap batch always did.
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => mock.attendanceCalls.length, PAST_WINDOW).toBe(2);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
  });

  /**
   * Issue #866: the count is a promise about what the tap will mark. A held
   * seat is one the bulk endpoint refuses outright (#672), and an expected
   * absence is the parent saying the student isn't coming — neither belongs
   * in "mark rest present", and neither should have to be discovered by a
   * rejected batch.
   */
  test("held and expected-absence rows are out of the count and the batch", async ({
    page,
    mock,
  }) => {
    mock.today.sessions[0].roster.push(
      {
        student_id: "st-held",
        full_name: "Carla",
        enrollment_status: "held",
        hold_return_on: "2026-10-15",
      },
      {
        student_id: "st-away",
        full_name: "Dev",
        enrollment_status: "active",
        expected_absence: true,
      },
    );

    await page.goto("/coach/sessions/s-today-1");
    // Both rows are on the roster and tappable one at a time — only the
    // bulk batch skips them.
    await expect(page.getByTestId("roster-st-held")).toBeVisible();
    await expect(page.getByTestId("roster-st-away")).toBeVisible();

    const bulkButton = page.getByTestId("mark-all-present");
    await expect(bulkButton).toContainText("Mark rest present (2)");
    await bulkButton.click();
    await expect(page.getByTestId("mark-all-undo-bar")).toContainText("Marked 2 present");

    await expect.poll(() => mock.bulkAttendanceCalls.length, PAST_WINDOW).toBe(1);
    expect(mock.bulkAttendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      entries: [
        { student_id: "st1", status: "present" },
        { student_id: "st2", status: "present" },
      ],
    });
    // The count was the truth: nothing was rejected, and the two skipped
    // rows are still unmarked rather than silently marked present.
    await expect(page.getByTestId("bulk-attendance-error")).toHaveCount(0);
    await expect(page.getByTestId("mark-st-held-present")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(page.getByTestId("mark-st-away-present")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    // Nothing is left for a BATCH — the two skipped rows take an individual
    // tap if they turn up — which is the same disabled state #672 leaves
    // behind for a row the server named ineligible.
    await expect(bulkButton).toContainText("All marked");
    await expect(bulkButton).toBeDisabled();
  });
});
