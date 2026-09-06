/**
 * Wave 1A E2E tests for Coach Today.
 *
 * Per docs/tickets/wave-1a-coach-today.md (W1A-17):
 * - online happy path
 * - offline first marks queue on the device and replay on reconnect (slice 3,
 *   docs/offline-policy.md case #1); saved marks stay read-only offline; a
 *   queued mark survives a reload (hydrated from IndexedDB on mount)
 * - coach notes carry a visibility flag (private by default, share switch)
 * - role-rejection (parent token → coach route → 404 / redirect)
 *
 * iOS install instructions / Android install / SW update toast are
 * verified manually on real devices during W1A-20; the install card test
 * here covers the rendered card, not the OS-level prompt.
 */

import type { Locator } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

/** Phone tap target: at least 44px tall and wide (Apple HIG / WCAG 2.5.5). */
async function expectTouchTarget(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  expect(box, "element has a layout box").not.toBeNull();
  expect(box!.height).toBeGreaterThanOrEqual(44);
  expect(box!.width).toBeGreaterThanOrEqual(44);
}

test.describe("Coach Today", () => {
  test("renders today with seeded sessions", async ({ page, mock }) => {
    void mock;
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    await expect(page.getByTestId("session-s-today-1")).toContainText("Junior A");
  });

  test("mark-attendance happy path", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1");
    await page.getByTestId("mark-st1-present").click();
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    expect(mock.attendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      student_id: "st1",
      status: "present",
    });
  });

  test("mark all present bulk-marks only unmarked students", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1");

    // Mark st1 absent individually first; bulk should then only cover st2.
    await page.getByTestId("mark-st1-absent").click();
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    await expect(page.getByTestId("mark-st1-absent")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    const bulkButton = page.getByTestId("mark-all-present");
    await expect(bulkButton).toContainText("Mark all present (1)");
    await bulkButton.click();

    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(1);
    expect(mock.bulkAttendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      entries: [{ student_id: "st2", status: "present" }],
    });

    await expect(page.getByTestId("mark-st2-present")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(bulkButton).toBeDisabled();
    await expect(bulkButton).toContainText("All marked");
  });

  test("offline queues a first mark on the phone and syncs it on reconnect", async ({
    page,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();

    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-indicator")).toBeVisible();
    // Nobody is marked yet, so there is nothing a queued correction could
    // clobber — no "saved marks" hint and every button stays tappable.
    await expect(page.getByTestId("offline-write-blocked")).toHaveCount(0);
    await expect(page.getByTestId("mark-st1-present")).toBeEnabled();

    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
    await expect(page.getByTestId("queued-count")).toContainText("1");
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "true");
    expect(mock.attendanceCalls).toHaveLength(0);

    // Second tap while offline rewrites the queued mark (policy case #1).
    await page.getByTestId("mark-st1-absent").click();
    await expect(page.getByTestId("mark-st1-absent")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("queued-count")).toContainText("1");
    expect(mock.attendanceCalls).toHaveLength(0);

    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    expect(mock.attendanceCalls[0]).toMatchObject({
      occurrence_id: "occ-today-1",
      session_id: "s-today-1",
      student_id: "st1",
      status: "absent",
    });
    expect(typeof mock.attendanceCalls[0].mutation_id).toBe("string");
    await expect(page.getByTestId("mark-queued-st1")).toHaveCount(0);
    await expect(page.getByTestId("queued-count")).toHaveCount(0);
    await expect(page.getByTestId("mark-st1-absent")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("offline-indicator")).toHaveCount(0);
    // The sync has settled (chip gone, indicator cleared): exactly one replay
    // went out — no second POST from a racing reconnect path or the plain
    // online mutation.
    expect(mock.attendanceCalls).toHaveLength(1);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
  });

  test("a queued mark survives a reload and is hydrated from the device queue", async ({
    page,
    mock,
  }) => {
    // The server is down for the replay, so the mark stays queued across the
    // reload (sync.ts keeps 5xx failures in the queue) and the page must show
    // it from IndexedDB on mount rather than from in-memory state.
    mock.attendanceResponder = () => ({
      status: 503,
      body: { error: { code: "Unavailable", message: "down", details: {} } },
    });
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-indicator")).toBeVisible();
    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
    expect(mock.attendanceCalls).toHaveLength(0);

    await page.reload();
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
    await expect(page.getByTestId("queued-count")).toContainText("1");
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "true");
    // navigator.onLine is true after the reload, so the layout's auto-sync
    // tried the replay and the 503 left it queued; nothing was bulk-marked.
    await expect.poll(() => mock.attendanceCalls.length).toBeGreaterThanOrEqual(1);
    expect(mock.attendanceCalls[0]).toMatchObject({ student_id: "st1", status: "present" });
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
  });

  test("offline keeps a saved mark read-only but still queues the rest", async ({
    page,
    mock,
  }) => {
    mock.today.sessions[0].roster[1].attendance_status = "present";
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("mark-st2-present")).toHaveAttribute("aria-pressed", "true");

    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await expect(page.getByTestId("offline-indicator")).toBeVisible();
    await expect(page.getByTestId("offline-write-blocked")).toBeVisible();
    await expect(page.getByTestId("mark-st2-absent")).toBeDisabled();
    await expect(page.getByTestId("mark-st2-present")).toBeDisabled();

    const bulkButton = page.getByTestId("mark-all-present");
    await expect(bulkButton).toContainText("Mark all present (1)");
    await bulkButton.click();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "true");
    await expect(bulkButton).toContainText("All marked");
    expect(mock.attendanceCalls).toHaveLength(0);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);

    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    expect(mock.attendanceCalls[0]).toMatchObject({ student_id: "st1", status: "present" });
    await expect(page.getByTestId("mark-queued-st1")).toHaveCount(0);
    await expect(page.getByTestId("queued-count")).toHaveCount(0);
    // Settled: the one queued student replayed once over the single-mark
    // endpoint; reconnecting never fires the bulk endpoint.
    expect(mock.attendanceCalls).toHaveLength(1);
    expect(mock.bulkAttendanceCalls).toHaveLength(0);
  });

  test("a queued mark the server rejects lands in the tray with a reason", async ({
    page,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.StudentNotEnrolled",
          message: "student not enrolled",
          details: {},
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-present").click();
    await expect(page.getByTestId("mark-queued-st1")).toBeVisible();

    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    const error = page.getByTestId("mark-error-st1");
    await expect(error).toContainText("isn't actively enrolled");
    await expect(error.getByRole("link", { name: "Open Needs review" })).toHaveAttribute(
      "href",
      "/coach/needs-review",
    );
    await expect(page.getByTestId("mark-queued-st1")).toHaveCount(0);
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "false");
  });

  test("attendance controls are phone-sized and the row never overflows", async ({ page, mock }) => {
    void mock;
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("session-detail")).toBeVisible();
    for (const id of ["mark-st1-present", "mark-st1-absent", "mark-all-present"]) {
      await expectTouchTarget(page.getByTestId(id));
    }
    const noOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    );
    expect(noOverflow).toBe(true);
  });

  test("a coach can save a note shared with the parent", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1");
    await page.getByTestId("roster-st1").getByRole("button", { name: "Note", exact: true }).click();
    const share = page.getByTestId("note-share-st1");
    await expect(share).not.toBeChecked();
    await expect(page.getByTestId("note-private-hint")).toHaveCount(0);
    await share.check();
    await page.getByPlaceholder("Progress note for Alice…").fill("Great footwork today");
    await page.getByRole("button", { name: "Save note" }).click();
    await expect.poll(() => mock.progressNoteCalls.length).toBe(1);
    expect(mock.progressNoteCalls[0]).toEqual({
      student_id: "st1",
      body: "Great footwork today",
      visibility: "shared",
    });

    // The box closes on save; reopening lists the note with its audience.
    await expect(page.getByTestId("note-share-st1")).toHaveCount(0);
    await page.getByTestId("roster-st1").getByRole("button", { name: "Note", exact: true }).click();
    await expect(page.getByTestId("note-note-1")).toContainText("Great footwork today");
    await expect(page.getByTestId("note-visibility-note-1")).toHaveText(/shared with parent/i);
  });

  test("notes default to private and the toggle flips visibility over PATCH", async ({
    page,
    mock,
  }) => {
    mock.progressNotes.push({
      note_id: "note-seeded",
      session_id: "s-today-1",
      student_id: "st1",
      coach_id: "user-coach-e2e",
      body: "Needs to work on the serve",
      created_at: new Date().toISOString(),
      visibility: "private",
    });
    await page.goto("/coach/sessions/s-today-1");
    await page.getByTestId("roster-st1").getByRole("button", { name: "Note", exact: true }).click();
    await expect(page.getByTestId("note-visibility-note-seeded")).toHaveText(/private/i);

    const toggle = page.getByTestId("note-share-toggle-note-seeded");
    await expectTouchTarget(toggle);
    await expect(toggle).toHaveText("Share");
    await toggle.click();
    await expect.poll(() => mock.noteVisibilityCalls.length).toBe(1);
    expect(mock.noteVisibilityCalls[0]).toEqual({ note_id: "note-seeded", visibility: "shared" });
    await expect(page.getByTestId("note-visibility-note-seeded")).toHaveText(/shared with parent/i);
    await expect(toggle).toHaveText("Make private");

    await toggle.click();
    await expect.poll(() => mock.noteVisibilityCalls.length).toBe(2);
    expect(mock.noteVisibilityCalls[1]).toEqual({ note_id: "note-seeded", visibility: "private" });
    await expect(page.getByTestId("note-visibility-note-seeded")).toHaveText(/private/i);

    // A plain save without the switch sends the private default explicitly.
    await page.getByPlaceholder("Progress note for Alice…").fill("Quiet session");
    await page.getByRole("button", { name: "Save note" }).click();
    await expect.poll(() => mock.progressNoteCalls.length).toBe(1);
    expect(mock.progressNoteCalls[0]).toMatchObject({ student_id: "st1", visibility: "private" });
  });

  test("server conflict on a plain mark is applied as a correction", async ({ page, mock }) => {
    // The mark already exists server-side (e.g. another device): the coach's
    // tap is a change, so the page must PATCH a correction instead of
    // leaving an error (#646).
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.ConflictAttendanceExists",
          message: "another mutation already recorded attendance",
          details: { existing_attendance_id: "att-existing" },
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await page.getByTestId("mark-st1-absent").click();
    await expect(page.getByTestId("mark-st1-absent")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("mark-error-st1")).toHaveCount(0);
    expect(mock.correctionCalls).toEqual([
      expect.objectContaining({ student_id: "st1", status: "absent" }),
    ]);
  });
});
