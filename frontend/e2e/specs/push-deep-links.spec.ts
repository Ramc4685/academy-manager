/**
 * Push deep links: every `data.url` a push now carries opens straight onto
 * the thing the push is about, and a link to something that is gone (or was
 * never this family's) lands on the page with a note instead of a dead end.
 *
 * Opens each URL directly, the way the app shell's `location.assign` does on
 * a tap. The admin `?dm=` thread link is covered by admin-messages.spec.ts and
 * the waitlist `?offer=` link by waitlist-offers.spec.ts.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const json = (route: Route, body: unknown) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function stubIdentity(page: Page, roles: string[]) {
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET"
      ? json(route, {
          user_id: `user-${roles[0]}-e2e`,
          email: `${roles[0]}@example.com`,
          academy_id: "academy-e2e",
          roles,
        })
      : route.fallback(),
  );
}

function inbox() {
  const at = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
  return [
    { message_id: "m-dm", kind: "dm", sender_persona: "admin", body: "Can Ava move to Thursdays?", created_at: at(5), read: false, author_display_name: "Sam Admin" },
    { message_id: "m-ann", kind: "announcement", sender_persona: "admin", body: "Courts are closed Friday for floor resurfacing.", created_at: at(60), read: true, author_display_name: "Sam Admin" },
    { message_id: "m-urgent", kind: "announcement", sender_persona: "coach", body: "No class tonight, the gym lost power.", created_at: at(90), read: true, scope_label: "Junior A", urgency: "urgent", author_display_name: "Coach Riya" },
  ];
}

async function stubInbox(page: Page, persona: "parent" | "coach") {
  await page.route(`**/api/v2/${persona}/messages/*/read`, (route) =>
    json(route, { status: "ok" }),
  );
  await page.route(`**/api/v2/${persona}/messages`, (route) =>
    route.request().method() === "GET" ? json(route, { messages: inbox() }) : route.fallback(),
  );
}

const CALENDAR_NOW = new Date("2026-11-17T12:00:00Z");

async function stubCalendar(page: Page) {
  await page.clock.setFixedTime(CALENDAR_NOW);
  await page.route("**/api/v2/parent/children", (route) =>
    json(route, {
      children: [
        { student_id: "st-1", full_name: "Ava Kim", lifecycle: "active", active_session_count: 1, attended_count: 3, absent_count: 0 },
      ],
    }),
  );
  const entry = (id: string, day: string, over: Record<string, unknown> = {}) => ({
    occurrence_id: id,
    session_id: "sess-1",
    session_title: "Junior A",
    location: "Court 1",
    start_at: `${day}T23:00:00Z`,
    end_at: `${day}T23:59:00Z`,
    status: "scheduled",
    coach_name: "Coach Riya",
    ...over,
  });
  await page.route("**/api/v2/parent/children/*/schedule*", (route) =>
    json(route, {
      entries: [
        entry("occ-1", "2026-11-18"),
        entry("occ-2", "2026-11-25", { status: "cancelled", cancellation_reason: "Gym not available" }),
        entry("occ-3", "2026-12-02"),
      ],
      total: 3,
      limit: 50,
      offset: 0,
    }),
  );
  await page.route("**/api/v2/parent/academy", (route) =>
    json(route, {
      display_name: "Aces Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
      schedule_published_through: "2026-12",
    }),
  );
}

test.describe("push deep links", () => {
  test("a message push opens the parent inbox on that message", async ({ page }, info) => {
    await stubIdentity(page, ["parent"]);
    await stubInbox(page, "parent");

    await page.goto("/parent/messages?message=m-urgent");

    const row = page.locator('[data-testid="message-row"][data-highlighted="true"]');
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("No class tonight");
    await expect(row).toBeInViewport();
    await expect(page.getByTestId("parent-message-missing")).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("parent-messages-linked.png"), fullPage: true });
  });

  test("a coach DM push opens the coach inbox on that message", async ({ page }, info) => {
    await stubIdentity(page, ["coach"]);
    await stubInbox(page, "coach");

    await page.goto("/coach/messages?message=m-dm");

    const row = page.locator('[data-testid="message-row"][data-highlighted="true"]');
    await expect(row).toContainText("Can Ava move to Thursdays?");
    await page.screenshot({ path: info.outputPath("coach-messages-linked.png"), fullPage: true });
  });

  test("a push for a deleted or someone else's message lands on the inbox with a note", async ({
    page,
  }, info) => {
    await stubIdentity(page, ["parent"]);
    await stubInbox(page, "parent");

    await page.goto("/parent/messages?message=m-not-yours");

    await expect(page.getByTestId("parent-message-missing")).toBeVisible();
    // S62: the two announcements list as rows; the DM sits in the academy thread.
    await expect(page.getByTestId("message-row")).toHaveCount(2);
    await expect(page.getByTestId("academy-bubble")).toHaveCount(1);
    await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("parent-messages-missing.png"), fullPage: true });
  });

  test("a cancellation push opens the calendar list on that date, even on a wide screen", async ({
    page,
  }, info) => {
    await stubIdentity(page, ["parent"]);
    await stubCalendar(page);
    // Wide screens default to the month grid; a linked date still opens the list.
    await page.setViewportSize({ width: 1280, height: 900 });

    await page.goto("/parent/calendar?occurrence=occ-2");

    const row = page.locator('[data-testid="schedule-row"][data-highlighted="true"]');
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Gym not available");
    await expect(page.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("schedule-occurrence-missing")).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: info.outputPath("parent-calendar-linked.png"), fullPage: true });
  });

  test("a cancellation push for a date not on this family's schedule shows a note", async ({
    page,
  }, info) => {
    await stubIdentity(page, ["parent"]);
    await stubCalendar(page);

    await page.goto("/parent/calendar?occurrence=occ-another-family");

    await expect(page.getByTestId("schedule-occurrence-missing")).toBeVisible();
    await expect(page.getByTestId("schedule-row")).toHaveCount(3);
    await page.screenshot({ path: info.outputPath("parent-calendar-missing.png"), fullPage: true });
  });

  test("a closure push opens the calendar", async ({ page }) => {
    await stubIdentity(page, ["parent"]);
    await stubCalendar(page);

    await page.goto("/parent/calendar");

    await expect(page.getByTestId("parent-schedule-list")).toBeVisible();
    await expect(page.getByTestId("schedule-occurrence-missing")).toHaveCount(0);
    await expect(page.locator('[data-highlighted="true"]')).toHaveCount(0);
  });
});
