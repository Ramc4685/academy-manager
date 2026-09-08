/**
 * Issue #672: make-up / trial attendees on the coach roster.
 *
 * A MAKE-UP row has no standing enrollment; "Mark all present" batches it
 * with everyone else and the server accepts it. When the server does refuse
 * the batch (422 naming ineligible rows), the coach sees who blocked it
 * instead of a silent failure, and the retry leaves those rows out.
 */

import { test, expect } from "../fixtures/mock-api";

test.describe("Coach make-up attendance", () => {
  test.beforeEach(async ({ mock }) => {
    mock.today.sessions[0].roster.push({
      student_id: "st-makeup",
      full_name: "Charlie",
      enrollment_status: "active",
      entry_source: "makeup",
    });
  });

  test("mark all present includes the MAKE-UP row and succeeds", async ({ page, mock }) => {
    await page.goto("/coach/sessions/s-today-1");
    await expect(page.getByTestId("roster-st-makeup")).toContainText("MAKE-UP");

    const bulkButton = page.getByTestId("mark-all-present");
    await expect(bulkButton).toContainText("Mark all present (3)");
    await bulkButton.click();

    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(1);
    expect(mock.bulkAttendanceCalls[0]).toMatchObject({
      session_id: "s-today-1",
      entries: [
        { student_id: "st1", status: "present" },
        { student_id: "st2", status: "present" },
        { student_id: "st-makeup", status: "present" },
      ],
    });
    await expect(page.getByTestId("mark-st-makeup-present")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(bulkButton).toContainText("All marked");
    await expect(page.getByTestId("bulk-attendance-error")).toHaveCount(0);
  });

  test("a 422 naming ineligible students is explained and excluded from the retry", async ({
    page,
    mock,
  }) => {
    mock.bulkAttendanceResponder = () => ({
      status: 422,
      body: {
        error: {
          code: "Coaching.BulkStudentNotEnrolled",
          message: "students not actively enrolled in session",
          details: { student_ids: ["st2"], occurrence_id: "occ-today-1" },
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");

    const bulkButton = page.getByTestId("mark-all-present");
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(1);

    const banner = page.getByTestId("bulk-attendance-error");
    await expect(banner).toContainText("Nothing was saved");
    await expect(banner).toContainText("Bob isn't eligible");
    await expect(page.getByTestId("mark-error-st2")).toContainText("no approved make-up");
    // Nothing was saved: the other rows are back to unmarked, and the
    // retry leaves Bob out.
    await expect(page.getByTestId("mark-st1-present")).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("mark-st-makeup-present")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await expect(bulkButton).toContainText("Mark all present (2)");

    mock.bulkAttendanceResponder = undefined;
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(2);
    expect(mock.bulkAttendanceCalls[1]).toMatchObject({
      entries: [
        { student_id: "st1", status: "present" },
        { student_id: "st-makeup", status: "present" },
      ],
    });
    await expect(page.getByTestId("bulk-attendance-error")).toHaveCount(0);
    // Bob stays out after the retry succeeds: the button does not offer a
    // "Mark all present (1)" that would only re-send him and 422 again.
    await expect(bulkButton).toContainText("All marked");
    await expect(bulkButton).toBeDisabled();
    await expect(page.getByTestId("mark-error-st2")).toContainText("no approved make-up");
    await expect(page.getByTestId("mark-st2-present")).toHaveAttribute("aria-pressed", "false");
  });

  test("a failed single tap on an eligible student does not shrink the retry", async ({
    page,
    mock,
  }) => {
    mock.bulkAttendanceResponder = () => ({
      status: 422,
      body: {
        error: {
          code: "Coaching.BulkStudentNotEnrolled",
          message: "students not actively enrolled in session",
          details: { student_ids: ["st2"], occurrence_id: "occ-today-1" },
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");

    const bulkButton = page.getByTestId("mark-all-present");
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(1);
    await expect(bulkButton).toContainText("Mark all present (2)");

    // Alice's own tap fails on the network: her row shows the error, but she
    // is still eligible and must stay in the batch.
    mock.attendanceResponder = () => ({
      status: 500,
      body: { error: { code: "Internal", message: "boom" } },
    });
    await page.getByTestId("mark-st1-present").click();
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    await expect(page.getByTestId("mark-error-st1")).toBeVisible();
    await expect(bulkButton).toContainText("Mark all present (2)");

    mock.attendanceResponder = undefined;
    mock.bulkAttendanceResponder = undefined;
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(2);
    expect(mock.bulkAttendanceCalls[1]).toMatchObject({
      entries: [
        { student_id: "st1", status: "present" },
        { student_id: "st-makeup", status: "present" },
      ],
    });
    await expect(bulkButton).toContainText("All marked");
    await expect(page.getByTestId("mark-error-st1")).toHaveCount(0);
  });

  test("a single tap that succeeds for the named student lets the batch reach everyone", async ({
    page,
    mock,
  }) => {
    mock.bulkAttendanceResponder = () => ({
      status: 422,
      body: {
        error: {
          code: "Coaching.BulkStudentNotEnrolled",
          message: "students not actively enrolled in session",
          details: { student_ids: ["st2"], occurrence_id: "occ-today-1" },
        },
      },
    });
    await page.goto("/coach/sessions/s-today-1");
    const bulkButton = page.getByTestId("mark-all-present");
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(1);
    await expect(bulkButton).toContainText("Mark all present (2)");

    // The admin fixed Bob's status meanwhile; the coach taps him directly.
    await page.getByTestId("mark-st2-present").click();
    await expect.poll(() => mock.attendanceCalls.length).toBe(1);
    await expect(page.getByTestId("mark-st2-present")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("mark-error-st2")).toHaveCount(0);
    await expect(bulkButton).toContainText("Mark all present (2)");

    mock.bulkAttendanceResponder = undefined;
    await bulkButton.click();
    await expect.poll(() => mock.bulkAttendanceCalls.length).toBe(2);
    await expect(bulkButton).toContainText("All marked");
  });
});
