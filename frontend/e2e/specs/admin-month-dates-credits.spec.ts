import { test, expect, type Page } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

/** Month dates (#1207): what a called-off date credited, and crediting a missed past date. */

const DAY = 86_400_000;
const at = (offsetDays: number) => {
  const d = new Date(Date.now() + offsetDays * DAY);
  d.setUTCHours(18, 0, 0, 0);
  return d.toISOString();
};
const PAST = at(-3);
const FUTURE = at(3);

const occ = (id: string, start: string, status = "scheduled", reason: string | null = null) => ({
  occurrence_id: id,
  session_id: "sess-1",
  start_at: start,
  end_at: new Date(Date.parse(start) + 3_600_000).toISOString(),
  status,
  cancellation_reason: reason,
  cancelled_at: null,
  scheduled_coach_id: "coach-1",
  actual_coach_id: null,
  substitute_coach_id: null,
  attendance_marked_count: 0,
  attendance_marked_by: [],
  attendance_last_marked_at: null,
  coach_attendance: [],
});

async function setup(page: Page, month: string, missedOver: Record<string, unknown> = {}) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [{ academy_id: ACADEMY_A, academy_name: "Test Academy", role: "owner" }]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (r) => fulfillJson(r, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (r) => fulfillJson(r, { counts: {}, total: 0 }));
  const status: Record<string, string> = {};
  const posts: { url: string; body: Record<string, unknown> }[] = [];
  await page.route(/\/api\/v2\/admin\/sessions(\?.*)?$/, (r) =>
    fulfillJson(r, {
      sessions: [
        {
          session_id: "sess-1", coach_id: "coach-1", coach_name: "Coach Sam", assistant_coach_ids: [],
          assistant_coach_names: [], title: "Thu Juniors", location: "Court 1", start_at: at(-60), end_at: at(60),
          days_of_week: ["thursday"], start_time: "18:00", end_time: "19:00", timezone: "UTC", capacity: 12,
          status: "scheduled", enrolled_count: 3, waitlist_count: 0, phase: "active",
        },
      ],
    }),
  );
  await page.route("**/api/v2/admin/sessions/sess-1/occurrences", (r) =>
    fulfillJson(r, {
      occurrences: [
        occ("occ-past", PAST, status["occ-past"] ?? "scheduled"),
        occ("occ-future", FUTURE, status["occ-future"] ?? "scheduled"),
      ],
    }),
  );
  await page.route("**/api/v2/admin/schedule/publish", (r) => fulfillJson(r, { published_through: null }));
  await page.route("**/api/v2/admin/session-occurrences/*/cancel", (r) => {
    status["occ-future"] = "cancelled";
    return fulfillJson(r, {
      occurrence: occ("occ-future", FUTURE, "cancelled", "Gym closed"),
      affected_enrollment_ids: ["e1", "e2", "e3"],
      roster_entries_removed: 0,
      makeups_reopened: 0,
      trials_reopened: 0,
      credits_issued: 2,
      credit_total_cents: 3500,
      credit_skips: { covered_by_free_classes: 1 },
      billing_result: "credited=2,skipped=1,override=written",
      notified: false,
    });
  });
  await page.route("**/api/v2/admin/session-occurrences/*/credit-missed", (r) => {
    const body = r.request().postDataJSON() as Record<string, unknown>;
    posts.push({ url: r.request().url(), body });
    if (!body.dry_run) status["occ-past"] = "cancelled";
    return fulfillJson(r, {
      occurrence_id: "occ-past",
      start_at: PAST,
      dry_run: Boolean(body.dry_run),
      families: body.dry_run
        ? [
            { enrollment_id: "e1", student_id: "s1", student_name: "Maya Test", amount_cents: 1750, outcome: "would_credit" },
            { enrollment_id: "e2", student_id: "s2", student_name: "Ava Demo", amount_cents: 0, outcome: "skipped:covered_by_free_classes" },
          ]
        : [],
      credits_issued: body.dry_run ? 0 : 1,
      credit_total_cents: 1750,
      credit_skips: { covered_by_free_classes: 1 },
      payroll_flag: "Adjust the coach's pay for this date by hand.",
      billing_result: body.dry_run ? null : "credited=1,skipped=1,override=written",
      ...missedOver,
    });
  });
  await page.goto("/admin/sessions/month-dates");
  await page.getByTestId("month-dates-month").fill(month);
  await expect(page.getByTestId("month-dates-list")).toBeVisible();
  return { errors, posts };
}

test.describe("Month dates credits", () => {
  test("calling off a date says what it credited and why some families got nothing", async ({ page }) => {
    const { errors } = await setup(page, FUTURE.slice(0, 7));
    await page.getByLabel("Thu Juniors has class").last().uncheck();
    await page.getByTestId("month-dates-save").click();
    await page.getByRole("dialog").getByRole("textbox").fill("Gym closed");
    await page.getByRole("button", { name: "Call off dates" }).click();
    await expect(page.getByTestId("month-dates-credit-row")).toContainText(
      "2 families credited, $35.00 in total. 1 family not credited: the month's free extra class covered it.",
    );
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("a missed past date previews the credits, then confirms and is marked No class", async ({ page }) => {
    const { errors, posts } = await setup(page, PAST.slice(0, 7));
    await page.getByTestId("credit-missed-occ-past").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Gym closed, found out late");
    await dialog.getByTestId("confirm-action-submit").click();
    const families = page.getByTestId("credit-missed-families");
    await expect(families).toContainText("Maya Test");
    await expect(families).toContainText("$17.50");
    await expect(families).toContainText("No credit: the month's free extra class covered it");
    await expect(families).toContainText("Adjust the coach's pay");
    expect(posts.map((p) => p.body.dry_run)).toEqual([true]);

    await dialog.getByTestId("confirm-action-submit").click();
    await expect(page.getByTestId("month-dates-credit-row")).toContainText("1 family credited, $17.50 in total.");
    await expect(page.getByTestId("month-dates-credit-row")).toContainText("Adjust the coach's pay");
    await expect(page.getByTestId("credit-missed-occ-past")).toHaveCount(0);
    expect(posts.map((p) => [p.body.dry_run, p.body.reason])).toEqual([
      [true, "Gym closed, found out late"],
      [false, "Gym closed, found out late"],
    ]);
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("a date billing never laid out cannot be confirmed", async ({ page }) => {
    const { errors, posts } = await setup(page, PAST.slice(0, 7), {
      families: [],
      credit_total_cents: 0,
      schedule_changed: true,
    });
    await page.getByTestId("credit-missed-occ-past").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Gym closed");
    await dialog.getByTestId("confirm-action-submit").click();
    await expect(dialog.getByRole("alert")).toContainText("schedule changed");
    await expect(dialog.getByTestId("confirm-action-submit")).toHaveText("Preview credits");
    await expect(page.getByTestId("credit-missed-families")).toHaveCount(0);
    expect(posts.every((p) => p.body.dry_run === true)).toBe(true);
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("a confirm whose billing did not run says so instead of no credits", async ({ page }) => {
    const { errors } = await setup(page, PAST.slice(0, 7), { billing_result: "billing_sync_failed" });
    await page.getByTestId("credit-missed-occ-past").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Gym closed");
    await dialog.getByTestId("confirm-action-submit").click();
    await expect(page.getByTestId("credit-missed-families")).toBeVisible();
    await dialog.getByTestId("confirm-action-submit").click();
    await expect(page.getByTestId("month-dates-credit-row")).toContainText("Check Payment system status");
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
