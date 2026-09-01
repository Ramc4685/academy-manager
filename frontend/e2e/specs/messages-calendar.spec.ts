/**
 * UIM13 — coach/parent Messages inbox + Calendar.
 *
 * Mocks the v2 BFF at the Playwright route layer (no real backend), the
 * same approach as parent-self-service.spec.ts. We import the mock-api
 * fixture's `test`/`expect` for convention parity; routes registered
 * inside each test win over the fixture's defaults because Playwright
 * resolves routes in reverse registration order.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

interface InboxMessage {
  message_id: string;
  kind: "dm" | "announcement";
  sender_persona: "admin" | "coach" | "parent";
  body: string;
  created_at: string;
  read: boolean;
  // #614 session announcements.
  scope_label?: string;
  urgency?: "routine" | "urgent";
  author_display_name?: string;
}

const ANNOUNCEMENT_BODY = "Tournament this Saturday";
const DM_BODY = "Please review the updated roster";
const URGENT_ANNOUNCEMENT_BODY = "Court 3 is closed tonight";

function seedMessages(): InboxMessage[] {
  const createdAt = new Date().toISOString();
  return [
    {
      message_id: "m-dm-1",
      kind: "dm",
      sender_persona: "admin",
      body: DM_BODY,
      created_at: createdAt,
      read: false,
    },
    {
      message_id: "m-ann-1",
      kind: "announcement",
      sender_persona: "admin",
      body: ANNOUNCEMENT_BODY,
      created_at: createdAt,
      read: true,
    },
    // #614 session announcement: carries the class label and an urgency.
    {
      message_id: "m-ann-session",
      kind: "announcement",
      sender_persona: "coach",
      body: URGENT_ANNOUNCEMENT_BODY,
      created_at: createdAt,
      read: true,
      scope_label: "Tuesday Juniors",
      urgency: "urgent",
      author_display_name: "Coach Riya",
    },
  ];
}

async function stubIdentity(page: Page, roles: string[]): Promise<void> {
  await page.route("**/api/v2/me", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user_id: `user-${roles[0]}-e2e`,
        email: `${roles[0]}@example.com`,
        academy_id: "academy-e2e",
        roles,
      }),
    });
  });
}

/**
 * Stub GET/POST for one persona's messages surface against a mutable
 * in-memory list, so mark-read genuinely persists across a reload the way
 * `$addToSet` on `read_by` does server-side.
 */
async function stubMessages(
  page: Page,
  persona: "coach" | "parent",
): Promise<{ readCalls: string[] }> {
  const messages = seedMessages();
  const readCalls: string[] = [];

  await page.route(`**/api/v2/${persona}/messages/*/read`, async (route: Route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const match = /\/messages\/([^/]+)\/read/.exec(route.request().url());
    const messageId = match ? decodeURIComponent(match[1]) : "";
    readCalls.push(messageId);
    const target = messages.find((m) => m.message_id === messageId);
    if (target) target.read = true;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    });
  });

  await page.route(`**/api/v2/${persona}/messages`, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ messages }),
    });
  });

  return { readCalls };
}

test.describe("coach messages inbox", () => {
  test("renders DMs and announcements, and mark-read persists", async ({ page }) => {
    await stubIdentity(page, ["coach"]);
    const { readCalls } = await stubMessages(page, "coach");

    await page.goto("/coach/messages");

    await expect(page.getByTestId("coach-messages")).toBeVisible();
    await expect(page.getByTestId("coach-message-list")).toContainText(DM_BODY);
    await expect(page.getByTestId("coach-message-list")).toContainText(ANNOUNCEMENT_BODY);

    // The one unread DM is marked read on open; the already-read
    // announcement is not re-sent.
    await expect.poll(() => readCalls).toEqual(["m-dm-1"]);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);

    // Reload: the server-side read state persisted, so nothing is unread
    // and no duplicate mark-read fires.
    await page.reload();
    await expect(page.getByTestId("coach-message-list")).toContainText(DM_BODY);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);
    expect(readCalls).toEqual(["m-dm-1"]);
  });

  test("shows an empty state when there are no messages", async ({ page }) => {
    await stubIdentity(page, ["coach"]);
    await page.route("**/api/v2/coach/messages", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ messages: [] }),
      });
    });

    await page.goto("/coach/messages");
    await expect(page.getByTestId("coach-messages")).toContainText("No messages yet");
  });
});

test.describe("session announcements in the inbox (#614)", () => {
  test("a session announcement shows its class label and an urgent chip", async ({
    page,
  }) => {
    await stubIdentity(page, ["parent"]);
    await stubMessages(page, "parent");

    await page.goto("/parent/messages");

    const row = page
      .getByTestId("message-row")
      .filter({ hasText: URGENT_ANNOUNCEMENT_BODY });
    await expect(row).toBeVisible();
    // The class label is what tells a family WHICH class this is about.
    await expect(row.getByTestId("message-scope-label")).toHaveText(
      "Tuesday Juniors",
    );
    await expect(row.getByTestId("urgent-chip")).toBeVisible();

    // The academy-wide announcement is unchanged: no label, no urgent chip.
    const academyWide = page
      .getByTestId("message-row")
      .filter({ hasText: ANNOUNCEMENT_BODY });
    await expect(academyWide.getByTestId("message-scope-label")).toHaveCount(0);
    await expect(academyWide.getByTestId("urgent-chip")).toHaveCount(0);
  });
});

test.describe("parent messages inbox", () => {
  test("renders DMs and announcements, and mark-read persists", async ({ page }) => {
    await stubIdentity(page, ["parent"]);
    const { readCalls } = await stubMessages(page, "parent");

    await page.goto("/parent/messages");

    await expect(page.getByTestId("parent-messages")).toBeVisible();
    await expect(page.getByTestId("parent-message-list")).toContainText(DM_BODY);
    await expect(page.getByTestId("parent-message-list")).toContainText(ANNOUNCEMENT_BODY);

    await expect.poll(() => readCalls).toEqual(["m-dm-1"]);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);

    await page.reload();
    await expect(page.getByTestId("parent-message-list")).toContainText(DM_BODY);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);
    expect(readCalls).toEqual(["m-dm-1"]);
  });
});

test.describe("calendar smoke", () => {
  test("coach calendar renders the schedule grid", async ({ page }) => {
    await stubIdentity(page, ["coach"]);
    await stubMessages(page, "coach");

    const start = new Date();
    start.setHours(9, 0, 0, 0);
    const end = new Date(start.getTime() + 60 * 60 * 1000);

    await page.route("**/api/v2/coach/sessions", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sessions: [
            {
              session_id: "sess-1",
              occurrence_id: "occ-1",
              title: "Junior A",
              location: "Court 1",
              timezone: "America/Chicago",
              start_at: start.toISOString(),
              end_at: end.toISOString(),
            },
          ],
        }),
      });
    });

    await page.goto("/coach/calendar");
    await expect(page.getByTestId("coach-calendar")).toBeVisible();
    await expect(page.getByTestId("calendar-grid")).toBeVisible();
    await expect(page.getByTestId("calendar-grid")).toContainText("Junior A");
  });

  test("parent calendar merges every child's schedule", async ({ page }) => {
    await stubIdentity(page, ["parent"]);
    await stubMessages(page, "parent");

    const start = new Date();
    start.setHours(10, 0, 0, 0);
    const end = new Date(start.getTime() + 60 * 60 * 1000);

    await page.route("**/api/v2/parent/children", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          children: [
            {
              student_id: "st-1",
              full_name: "Ava Kim",
              status: "active",
              active_session_count: 1,
              attended_count: 3,
              absent_count: 0,
            },
          ],
        }),
      });
    });

    await page.route("**/api/v2/parent/children/*/schedule*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          entries: [
            {
              occurrence_id: "occ-100",
              session_id: "sess-1",
              session_title: "Junior Beginners",
              location: "Court 1",
              start_at: start.toISOString(),
              end_at: end.toISOString(),
              status: "scheduled",
              coach_name: "Coach Lee",
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        }),
      });
    });

    await page.goto("/parent/calendar");
    await expect(page.getByTestId("parent-calendar")).toBeVisible();
    await expect(page.getByTestId("calendar-child-legend")).toContainText("Ava Kim");
    await expect(page.getByTestId("calendar-grid")).toContainText("Junior Beginners");
  });
});
