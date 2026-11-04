/**
 * People CRM L3a: Came / Didn't come on a trial.
 *
 * Coach Today: a trial row of the coach's class carries Came / Didn't come
 * buttons (keyboard operable); "Didn't come" asks for a second press before it
 * saves. Admin Inbox (phone layout on the mobile projects): an approved trial
 * row offers Came / Didn't come in its actions, and "Didn't come" is
 * confirmed in a dialog. The backend is stubbed; its rules are covered by
 * backend/v2/tests (unit, interface and real-mongod contract tests).
 */

import type { Page, Route } from "@playwright/test";

import { test, expect } from "../fixtures/mock-api";

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function recordOutcomes(page: Page, pattern: string): Array<{ url: string; body: unknown }> {
  const calls: Array<{ url: string; body: unknown }> = [];
  void page.route(pattern, (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = JSON.parse(route.request().postData() ?? "{}") as { outcome: string };
    calls.push({ url: route.request().url(), body });
    const requestId = decodeURIComponent(route.request().url().split("/").at(-2) ?? "");
    return fulfillJson(route, { request_id: requestId, status: "completed", outcome: body.outcome });
  });
  return calls;
}

test("coach records Came and a confirmed Didn't come on a trial row", async ({ page, mock }) => {
  mock.today.sessions[0].roster.push({
    student_id: "st-trial",
    full_name: "Trial Kid",
    enrollment_status: null,
    entry_source: "trial",
    trial_request_id: "tr-1",
    trial_outcome: null,
  } as never);
  const calls = recordOutcomes(page, "**/api/v2/coach/trials/*/outcome");

  await page.goto("/coach/sessions/s-today-1");
  const control = page.getByTestId("trial-outcome-tr-1");
  await expect(control).toBeVisible();
  // Regular rows have no trial control.
  await expect(page.getByTestId("roster-st1").getByRole("group", { name: /Trial outcome/ })).toHaveCount(0);

  // Keyboard: focus Came and press Enter.
  await control.getByRole("button", { name: "Came" }).focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].url).toContain("/api/v2/coach/trials/tr-1/outcome");
  expect(calls[0].body).toEqual({ outcome: "came" });
  await expect(control.getByRole("button", { name: "Came" })).toHaveAttribute("aria-pressed", "true");

  // Didn't come needs a second, explicit press.
  await control.getByRole("button", { name: "Didn't come" }).click();
  await expect(control).toContainText("Mark Trial Kid as didn't come?");
  expect(calls.length).toBe(1);
  await control.getByRole("button", { name: "Cancel" }).click();
  await control.getByRole("button", { name: "Didn't come" }).click();
  await control.getByRole("button", { name: "Yes, didn't come" }).click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls[1].body).toEqual({ outcome: "no_show" });
});

const APPROVED_TRIAL = {
  request_id: "tr-9",
  student_ref: "prospective",
  student_id: null,
  prospective_child_name: "Sample Child",
  prospective_child_dob: null,
  requested_session_id: "session-1",
  preferred_start: "2026-09-20",
  preferred_end: "2026-09-30",
  status: "approved",
  assigned_occurrence_id: "occ-1",
  linked_application_id: null,
  denial_reason: null,
  decided_by: "admin-1",
  decided_at: "2026-09-18T12:00:00Z",
  created_at: "2026-09-17T12:00:00Z",
  requested_session_title: "Wednesday Beginner",
  assigned_occurrence_start_at: "2026-09-23T23:00:00Z",
  student_full_name: null,
  outcome: null,
  outcome_by: null,
  outcome_at: null,
};

test("admin Inbox records a confirmed Didn't come on an approved trial", async ({ page, mock }) => {
  mock.me = { user_id: "admin-e2e", email: "admin@example.com", academy_id: "academy-e2e", roles: ["admin"] };
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Rally Academy",
          academy_slug: "academy-e2e",
          roles: ["admin"],
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: { trials: 1 }, total: 1 }),
  );
  await page.route("**/api/v2/admin/messages*", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/academy", (route) =>
    fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Rally Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    }),
  );
  await page.route("**/api/v2/admin/self-service/trials*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { trials: [APPROVED_TRIAL] });
  });
  const calls = recordOutcomes(page, "**/api/v2/admin/self-service/trials/*/outcome");

  await page.goto("/admin/inbox?tab=trials");
  const row = page.getByTestId("admin-trials-row-tr-9");
  await expect(row).toBeVisible();

  const phone = await page.getByTestId("admin-trials-phone-list").count();
  if (phone > 0) {
    await page.getByTestId("admin-trials-actions-tr-9").click();
    await page.getByRole("menuitem", { name: "Didn't come" }).click();
  } else {
    await page.getByTestId("admin-trials-no-show-tr-9").click();
  }
  await expect(page.getByTestId("no-show-confirm-text")).toContainText("Sample Child");
  expect(calls.length).toBe(0);
  await page.getByTestId("no-show-confirm").click();
  await expect.poll(() => calls.length).toBe(1);
  expect(calls[0].url).toContain("/api/v2/admin/self-service/trials/tr-9/outcome");
  expect(calls[0].body).toEqual({ outcome: "no_show" });
});
