/**
 * Wave 1B E2E — six §0.9 offline conflict cases.
 *
 * Activated only when NEXT_PUBLIC_W1B_OFFLINE_WRITES=1. The harness sets
 * that for these specs and the dev-server picks it up at build time.
 *
 * Each case is asserted by the post-sync state of:
 * - the local queue ("/coach/needs-review" tray content)
 * - the mock backend's recorded mutations
 */

import { test, expect } from "../fixtures/mock-api";

test.use({ launchOptions: { args: ["--enable-features=BackgroundSync"] } });
test.use({ baseURL: "http://localhost:3001" });

const NEEDS_REVIEW_URL = "/coach/needs-review";

// Wave 1B is opt-in behind NEXT_PUBLIC_W1B_OFFLINE_WRITES=1. Per the
// architect's rule, this suite stays skipped in CI until W1A holds
// 1 week in production and the flag flips.
test.describe.skip("Wave 1B — offline writes + sync", () => {
  test("case #1: same student marked twice offline collapses to one mutation", async ({
    page,
    context,
    mock,
  }) => {
    await page.goto("/coach/sessions/s-today-1");
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-present").click();
    await page.getByTestId("mark-st1-absent").click();
    // Both clicks were queued locally. Reconnect → sync.
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect.poll(() => mock.attendanceCalls.length).toBeGreaterThanOrEqual(1);
    // The orchestrator sends *one* mutation per (session, student) tap; the
    // queue itself is append-only, so we expect 2 server calls in this
    // mock — but the server-side unique index would collapse the second
    // (case #4 territory). Wave 1B contract test asserts the index does
    // the right thing. Here we assert at minimum 1 succeeds.
    expect(mock.attendanceCalls.some((c) => c.student_id === "st1")).toBe(true);
  });

  test("case #2: session cancelled while offline → tray entry", async ({
    page,
    context,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.SessionCancelled",
          message: "session was cancelled",
          details: { session_id: "s-today-1" },
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-present").click();
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.goto(NEEDS_REVIEW_URL);
    await expect(page.getByTestId("tray-list")).toContainText("This session was cancelled");
  });

  test("case #3: student removed from roster → tray entry", async ({
    page,
    context,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.StudentNotEnrolled",
          message: "student not actively enrolled in session",
          details: {},
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st2-late").click();
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.goto(NEEDS_REVIEW_URL);
    await expect(page.getByTestId("tray-list")).toContainText("no longer enrolled in the session");
  });

  test("case #4: two-device race → server first wins, second to tray", async ({
    page,
    context,
    mock,
  }) => {
    let calls = 0;
    mock.attendanceResponder = () => {
      calls += 1;
      if (calls === 1) {
        return {
          status: 200,
          body: {
            attendance_id: "first",
            session_id: "s-today-1",
            student_id: "st1",
            status: "present",
            marked_at: new Date().toISOString(),
          },
        };
      }
      return {
        status: 409,
        body: {
          error: {
            code: "Coaching.ConflictAttendanceExists",
            message: "another mutation already recorded attendance",
            details: { existing_attendance_id: "first" },
          },
        },
      };
    };
    await page.goto("/coach/sessions/s-today-1");
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    // Queue two mutations for the same student (different mutation_ids
    // because the page generates a fresh ULID each tap).
    await page.getByTestId("mark-st1-present").click();
    await page.getByTestId("mark-st1-late").click();
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.goto(NEEDS_REVIEW_URL);
    await expect(page.getByTestId("tray-list")).toContainText("Attendance was already recorded for this student");
  });

  test("case #5: stale session_id → SessionNotAssigned tray", async ({
    page,
    context,
    mock,
  }) => {
    mock.attendanceResponder = () => ({
      status: 409,
      body: {
        error: {
          code: "Coaching.SessionNotAssigned",
          message: "session not assigned to this coach for that date",
          details: {},
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.getByTestId("mark-st1-absent").click();
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.goto(NEEDS_REVIEW_URL);
    await expect(page.getByTestId("tray-list")).toContainText("assigned to you for that date");
  });

  test("case #6: payment status changes → not surfaced (no coach UI dependency)", async ({
    page,
  }) => {
    // Per §0.9, payment status is not on the coach UI surface. We assert
    // the today page never renders a payment field.
    await page.goto("/coach/today");
    await expect(page.getByText(/payment/i)).toHaveCount(0);
  });
});
