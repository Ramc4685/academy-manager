/**
 * Parent self-service — absences, makeups, and enrollment self-cancel.
 *
 * Mocks the v2 BFF at the Playwright route layer (no real backend), the
 * same approach as coach-offline-writes.spec.ts / fixtures/mock-api.ts.
 * We import that fixture's `test`/`expect` for convention parity, but
 * re-register `**\/api/v2/me` with a `parent` role — Playwright resolves
 * routes in reverse registration order, so the route added inside each
 * test here wins over the fixture's default coach identity.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Route } from "@playwright/test";

const STUDENT_ID = "st-1";
const STUDENT_NAME = "Ava Kim";
const ENROLLMENT_ID = "enr-1";
const SESSION_TITLE = "Junior Beginners";

async function stubParentIdentity(page: import("@playwright/test").Page): Promise<void> {
  await page.route("**/api/v2/me", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: "user-parent-e2e",
        email: "parent@example.com",
        academy_id: "academy-e2e",
        roles: ["parent"],
      }),
    });
  });
}

async function stubAcademyAndChildren(page: import("@playwright/test").Page): Promise<void> {
  // X2: the Requests page also reads the family's waitlist offers. None
  // here, so the section stays hidden and these specs see the page as before.
  await page.route("**/api/v2/parent/waitlist", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ entries: [] }),
    });
  });

  await page.route("**/api/v2/parent/academy", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        display_name: "Aces Academy",
        timezone: "America/Chicago",
        contact_email: null,
        contact_phone: null,
        hours_text: null,
        address: null,
        logo_url: null,
      }),
    });
  });

  await page.route("**/api/v2/parent/children", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        children: [
          {
            student_id: STUDENT_ID,
            full_name: STUDENT_NAME,
            lifecycle: "active",
            active_session_count: 1,
            attended_count: 5,
            absent_count: 1,
          },
        ],
      }),
    });
  });
}

test.describe("parent self-service — absences", () => {
  test.beforeEach(async ({ page }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);
    await page.route(`**/api/v2/parent/children/${STUDENT_ID}/schedule`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          entries: [
            {
              occurrence_id: "occ-100",
              session_id: "sess-1",
              session_title: SESSION_TITLE,
              location: "Court 1",
              start_at: "2026-07-14T18:00:00Z",
              end_at: "2026-07-14T19:00:00Z",
              status: "scheduled",
              coach_name: "Coach Sam",
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      });
    });
  });

  test("shows an existing absence notice", async ({ page }) => {
    await page.route("**/api/v2/parent/absences", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          notices: [
            {
              notice_id: "notice-1",
              student_id: STUDENT_ID,
              occurrence_id: "occ-050",
              session_id: "sess-1",
              submitted_by: "parent-1",
              submitted_at: "2026-07-10T12:00:00Z",
              notice_window_met: true,
            },
          ],
        }),
      });
    });

    await page.goto("/parent/requests");
    await expect(page.getByTestId("parent-requests")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Absences", selected: true })).toBeVisible();
    await expect(page.getByText("My absence notices")).toBeVisible();
    await expect(page.getByText("ON TIME")).toBeVisible();
  });

  test("submitting an absence on time shows a success confirmation", async ({ page }) => {
    await page.route("**/api/v2/parent/absences", async (route: Route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ notices: [] }),
        });
      }
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            notice_id: "notice-2",
            student_id: STUDENT_ID,
            occurrence_id: "occ-100",
            session_id: "sess-1",
            submitted_by: "parent-1",
            submitted_at: new Date().toISOString(),
            notice_window_met: true,
          }),
        });
      }
      return route.fallback();
    });

    await page.goto("/parent/requests");
    // The "Child" and "Upcoming class" <select>s both nest their placeholder
    // option text inside their wrapping <label>, so the browser's computed
    // accessible name for each includes that option text (e.g. "Select a
    // child"). getByLabel does a case-insensitive substring match, so
    // getByLabel("Child") also matches the "Upcoming class" select once its
    // placeholder reads "Select a child...". Target by combobox position
    // within the form instead, which is unambiguous.
    const absenceForm = page.locator("form");
    await absenceForm.getByRole("combobox").nth(0).selectOption(STUDENT_ID);
    await absenceForm.getByRole("combobox").nth(1).selectOption("occ-100");
    await page.getByRole("button", { name: "Report absence" }).click();

    await expect(page.getByRole("status")).toContainText("Absence notice submitted.");
  });

  test("shows the child's name on an absence notice row", async ({ page }) => {
    const CHILD_B_ID = "st-2";
    const CHILD_B_NAME = "Priya Nair";
    await page.route("**/api/v2/parent/children", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          children: [
            {
              student_id: STUDENT_ID,
              full_name: STUDENT_NAME,
              lifecycle: "active",
              active_session_count: 1,
              attended_count: 5,
              absent_count: 1,
            },
            {
              student_id: CHILD_B_ID,
              full_name: CHILD_B_NAME,
              lifecycle: "active",
              active_session_count: 1,
              attended_count: 3,
              absent_count: 0,
            },
          ],
        }),
      });
    });
    await page.route("**/api/v2/parent/absences", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          notices: [
            {
              notice_id: "notice-2",
              student_id: CHILD_B_ID,
              occurrence_id: "occ-051",
              session_id: "sess-2",
              submitted_by: "parent-1",
              submitted_at: "2026-07-11T12:00:00Z",
              notice_window_met: true,
            },
          ],
        }),
      });
    });

    await page.goto("/parent/requests");
    await expect(page.getByText("My absence notices")).toBeVisible();
    const noticeRow = page.locator("ul li").first();
    await expect(noticeRow).toContainText(CHILD_B_NAME);
  });

  test("submitting an absence inside the notice window shows a warning banner", async ({
    page,
  }) => {
    await page.route("**/api/v2/parent/absences", async (route: Route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ notices: [] }),
        });
      }
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            notice_id: "notice-3",
            student_id: STUDENT_ID,
            occurrence_id: "occ-100",
            session_id: "sess-1",
            submitted_by: "parent-1",
            submitted_at: new Date().toISOString(),
            notice_window_met: false,
          }),
        });
      }
      return route.fallback();
    });

    await page.goto("/parent/requests");
    const absenceForm = page.locator("form");
    await absenceForm.getByRole("combobox").nth(0).selectOption(STUDENT_ID);
    await absenceForm.getByRole("combobox").nth(1).selectOption("occ-100");
    await page.getByRole("button", { name: "Report absence" }).click();

    // Next.js's route announcer is also role="alert" and always present, so
    // scope to the warning banner's text rather than the bare role locator.
    await expect(
      page.getByRole("alert").filter({ hasText: "Submitted inside the notice window" }),
    ).toContainText("Submitted inside the notice window — makeup eligibility may be affected.");
  });
});

test.describe("parent self-service — all switches off", () => {
  test("shows an empty state instead of the Absences panel when every request tab is hidden", async ({
    page,
  }) => {
    await stubParentIdentity(page);
    await page.route("**/api/v2/parent/waitlist", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ entries: [] }),
      });
    });
    // can_report_absence and can_request_makeup off, and the Public page's
    // trials_open toggle (can_request_trial) also off: TABS is empty, and
    // the page must not fall back to rendering the Absences form (#P2).
    await page.route("**/api/v2/parent/academy", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          display_name: "Aces Academy",
          timezone: "America/Chicago",
          contact_email: null,
          contact_phone: null,
          hours_text: null,
          address: null,
          logo_url: null,
          self_service: {
            can_report_absence: false,
            can_request_makeup: false,
            can_request_pause: false,
            can_request_cancel: false,
            can_claim_waitlist_offer: false,
            can_request_trial: false,
          },
        }),
      });
    });
    await page.route("**/api/v2/parent/children", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ children: [] }),
      });
    });

    await page.goto("/parent/requests");
    await expect(page.getByTestId("parent-requests")).toBeVisible();

    // No tab strip and no Absences form.
    await expect(page.getByRole("tablist")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Report absence" })).toHaveCount(0);
    await expect(page.getByText("No requests available")).toBeVisible();
  });
});

function candidate(studentId: string, studentName: string, occurrenceId: string) {
  return {
    student_id: studentId,
    student_name: studentName,
    occurrence_id: occurrenceId,
    session_id: "sess-1",
    class_title: SESSION_TITLE,
    start_at: "2026-07-14T23:00:00Z",
    end_at: "2026-07-15T00:00:00Z",
    has_notice: false,
    expires_at: "2026-07-28T00:00:00Z",
  };
}

async function stubMakeupCandidates(
  page: import("@playwright/test").Page,
  candidates: Record<string, unknown>[] | "error",
): Promise<void> {
  await page.route("**/api/v2/parent/makeups/candidates", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    if (candidates === "error") {
      // A 4xx: the app's query client retries 5xx with backoff, which would
      // only delay the same error state past the assertion timeout.
      return route.fulfill({ status: 403, contentType: "application/json", body: "{}" });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ candidates }),
    });
  });
}

test.describe("parent self-service — makeups", () => {
  test("siblings who missed the same class are listed and requested separately (#1037)", async ({
    page,
  }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);
    await stubMakeupCandidates(page, [
      candidate(STUDENT_ID, STUDENT_NAME, "occ-050"),
      candidate("st-2", "Ben Kim", "occ-050"),
    ]);
    await page.route("**/api/v2/parent/makeups/eligible-targets*", (route: Route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: '{"targets":[]}' }),
    );
    const posted: Record<string, unknown>[] = [];
    await page.route("**/api/v2/parent/makeups", async (route: Route) => {
      if (route.request().method() === "POST") {
        posted.push(JSON.parse(route.request().postData() ?? "{}"));
        return route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: '{"makeups":[]}' });
    });

    await page.goto("/parent/requests");
    await page.getByRole("tab", { name: "Makeups" }).click();

    const picker = page.getByLabel("Missed class");
    await expect(picker.locator("option")).toHaveText([
      "Select a missed class",
      /^Ava Kim — Junior Beginners — /,
      /^Ben Kim — Junior Beginners — /,
    ]);
    await picker.selectOption("st-2:occ-050");
    await page.getByRole("button", { name: "Request makeup" }).click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0]).toMatchObject({ student_id: "st-2", missed_occurrence_id: "occ-050" });
  });

  test("a failed load says so instead of showing an empty list (#1041)", async ({ page }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);
    await stubMakeupCandidates(page, "error");

    await page.goto("/parent/requests");
    await page.getByRole("tab", { name: "Makeups" }).click();

    await expect(page.getByText("Could not load your missed classes.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(page.getByText("No missed classes available for a makeup request.")).toHaveCount(0);
  });

  test("submitting a makeup request shows a pending status chip", async ({ page }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);

    const makeups: Record<string, unknown>[] = [];

    await stubMakeupCandidates(page, [candidate(STUDENT_ID, STUDENT_NAME, "occ-050")]);

    await page.route("**/api/v2/parent/makeups/eligible-targets*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          targets: [
            {
              occurrence_id: "occ-200",
              session_id: "sess-2",
              title: "Junior Beginners Makeup",
              start_at: "2026-07-16T18:00:00Z",
              end_at: "2026-07-16T19:00:00Z",
              open_slots: 3,
            },
          ],
        }),
      });
    });

    await page.route("**/api/v2/parent/makeups", async (route: Route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ makeups }),
        });
      }
      if (route.request().method() === "POST") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        const created = {
          request_id: "mkup-1",
          student_id: body.student_id,
          missed_occurrence_id: body.missed_occurrence_id,
          requested_target_occurrence_id: body.requested_target_occurrence_id ?? null,
          status: "pending",
          expires_at: "2026-07-20T00:00:00Z",
          denial_reason: null,
          decided_by: null,
          decided_at: null,
          approved_target_occurrence_id: null,
          created_at: new Date().toISOString(),
        };
        makeups.push(created);
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(created),
        });
      }
      return route.fallback();
    });

    await page.goto("/parent/requests");
    await page.getByRole("tab", { name: "Makeups" }).click();

    await page.getByLabel("Missed class").selectOption(`${STUDENT_ID}:occ-050`);
    await page.getByLabel("Preferred makeup class (optional)").selectOption("occ-200");
    await page.getByRole("button", { name: "Request makeup" }).click();

    const makeupsList = page.locator("ul").filter({ hasText: "Requested" });
    await expect(makeupsList.getByText("PENDING")).toBeVisible();
    await expect(makeupsList).toContainText(STUDENT_NAME);
  });
});

test.describe("parent self-service — self-cancel enrollment", () => {
  test("shows the fee and timing before confirming, then confirms cancellation", async ({
    page,
  }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);

    await page.route("**/api/v2/parent/attendance", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ records: [] }),
      });
    });

    await page.route(`**/api/v2/parent/children/${STUDENT_ID}/schedule`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ entries: [], total: 0, limit: 20, offset: 0 }),
      });
    });

    await page.route("**/api/v2/parent/enrollments", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enrollments: [
            {
              enrollment_id: ENROLLMENT_ID,
              student_id: STUDENT_ID,
              student_name: STUDENT_NAME,
              session_id: "sess-1",
              session_title: SESSION_TITLE,
              status: "active",
              payment_mode: null,
              subscription_status: null,
            },
          ],
        }),
      });
    });

    await page.route(
      `**/api/v2/parent/enrollments/${ENROLLMENT_ID}/cancellation-preview`,
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            allowed: true,
            notice_met: false,
            fee_cents: 2500,
            effective_timing: "end_of_period",
            policy: { notice_days: 14, fee_cents: 2500 },
            blocked_reason: null,
            // Issue #675: the academy-local month end (Sept 30, Chicago).
            effective_at: "2026-10-01T04:59:59.999Z",
          }),
        });
      },
    );

    await page.route(
      `**/api/v2/parent/enrollments/${ENROLLMENT_ID}/self-cancel`,
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            enrollment_id: ENROLLMENT_ID,
            // Issue #675: end_of_period keeps the enrollment active until month end.
            status: "pending_cancellation",
            fee_cents: 2500,
            effective_timing: "end_of_period",
            cancelled_at: "2026-10-01T04:59:59.999Z",
            pending_cancellation_at: "2026-10-01T04:59:59.999Z",
          }),
        });
      },
    );

    await page.goto("/parent/children");
    await expect(page.getByTestId("parent-children")).toBeVisible();
    await page.getByRole("button", { name: "Cancel enrollment…" }).click();

    const dialog = page.getByRole("dialog", { name: `Cancel enrollment in ${SESSION_TITLE}` });
    await expect(dialog).toBeVisible();

    // Fee and timing must be visible before the parent confirms.
    await expect(dialog.getByText("Cancellation fee: $25.00")).toBeVisible();
    // Issue #675: human copy, never the raw policy token.
    const timing = dialog.getByTestId("cancellation-timing-copy");
    await expect(timing).toContainText("keeps their place through");
    await expect(timing).toContainText("30");
    await expect(timing).toContainText("October will not be billed");
    await expect(dialog.getByText("end_of_period")).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Confirm cancellation" })).toBeVisible();

    await dialog.getByPlaceholder("Why are you cancelling?").fill("Schedule conflict");
    await dialog.getByRole("button", { name: "Confirm cancellation" }).click();

    // Success is surfaced as a toast; the dialog closes.
    const toast = page.getByRole("status").filter({ hasText: "Cancellation scheduled" });
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("$25.00");
    await expect(dialog).not.toBeVisible();
  });
});

test.describe("parent self-service — progress", () => {
  test("renders progress notes", async ({ page }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);

    await page.route("**/api/v2/parent/progress", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          notes: [
            {
              note_id: "note-1",
              coach_name: "Coach Kim",
              student_name: STUDENT_NAME,
              created_at: new Date().toISOString(),
              session_title: SESSION_TITLE,
              body: "Great footwork this week.",
            },
          ],
        }),
      });
    });

    await page.goto("/parent/progress");

    await expect(page.getByTestId("parent-progress")).toBeVisible();
    await expect(page.getByText("Great footwork this week.")).toBeVisible();
  });
});

test.describe("parent self-service — re-enrol a departed child (#827)", () => {
  test("offers 'Enroll in a class' on the departed row, with the child pre-bound", async ({
    page,
  }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);

    await page.route("**/api/v2/parent/attendance", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ records: [] }),
      });
    });
    await page.route(`**/api/v2/parent/children/${STUDENT_ID}/schedule`, async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ entries: [], total: 0, limit: 20, offset: 0 }),
      });
    });
    // #826: the parent enrollments feed carries the latest departure per child.
    await page.route("**/api/v2/parent/enrollments", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enrollments: [
            {
              enrollment_id: ENROLLMENT_ID,
              student_id: STUDENT_ID,
              student_name: STUDENT_NAME,
              session_id: "sess-1",
              session_title: SESSION_TITLE,
              status: "dropped",
              departed: true,
              left_on: "2026-06-01T12:00:00Z",
              departure_reason: "Moved away",
              payment_mode: null,
              subscription_status: null,
            },
          ],
        }),
      });
    });

    await page.goto("/parent/children");
    await expect(page.getByTestId("parent-children")).toBeVisible();
    await expect(page.getByTestId(`enrollment-departed-${ENROLLMENT_ID}`)).toBeVisible();

    // A departed row is history: it must never offer a cancel (money) control.
    await expect(page.getByRole("button", { name: "Cancel enrollment…" })).toHaveCount(0);

    const reEnroll = page.getByTestId(`enrollment-re-enroll-${ENROLLMENT_ID}`);
    await expect(reEnroll).toBeVisible();
    await expect(reEnroll).toHaveAttribute("href", `/parent/onboarding?child=${STUDENT_ID}`);
  });
});
