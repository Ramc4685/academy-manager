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
            status: "active",
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

test.describe("parent self-service — makeups", () => {
  test("submitting a makeup request shows a pending status chip", async ({ page }) => {
    await stubParentIdentity(page);
    await stubAcademyAndChildren(page);

    const makeups: Record<string, unknown>[] = [];

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

    await page.getByLabel("Missed class").selectOption("occ-050");
    await page.getByLabel("Preferred makeup class (optional)").selectOption("occ-200");
    await page.getByRole("button", { name: "Request makeup" }).click();

    const makeupsList = page.locator("ul").filter({ hasText: "Requested" });
    await expect(makeupsList.getByText("PENDING")).toBeVisible();
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
            status: "cancelled",
            fee_cents: 2500,
            effective_timing: "end_of_period",
            cancelled_at: new Date().toISOString(),
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
    await expect(dialog.getByText("Effective timing: end_of_period")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Confirm cancellation" })).toBeVisible();

    await dialog.getByPlaceholder("Why are you cancelling?").fill("Schedule conflict");
    await dialog.getByRole("button", { name: "Confirm cancellation" }).click();

    await expect(dialog.getByRole("status")).toContainText("Enrollment cancelled");
    await expect(dialog.getByRole("status")).toContainText("$25.00");
  });
});
