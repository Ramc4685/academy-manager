import { test, expect, type Page } from "@playwright/test";

import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

/**
 * Admin direct messages (#864).
 *
 * Pins the three things the thread list has to tell an admin before they
 * click anything: that a family is waiting on a reply, what they last said,
 * and — on a phone — that both are reachable without scrolling past the
 * broadcast composer.
 *
 * Runs under chromium-mobile AND chromium-desktop (see `playwright.config.ts`
 * `testMatch`), and each test pins its own viewport so the responsive branch
 * under test is the one that renders in either project.
 */

const PARENT_ID = "par-1";
const PARENT_NAME = "Dana Whitfield";
const OLDER_BODY = "Can Ana switch to the Thursday class?";
const NEWER_BODY = "Actually, Friday suits us better.";

const PHONE = { width: 400, height: 900 };
const DESKTOP = { width: 1280, height: 900 };

interface StubbedMessage {
  message_id: string;
  kind: string;
  sender_id: string;
  recipient_id: string | null;
  counterparty_id: string | null;
  body: string;
  created_at: string;
  sent_at: string;
  is_broadcast: boolean;
  is_read: boolean;
}

/**
 * Newest first, the way `GET /admin/messages` sorts. The order matters: the
 * old grouping built a `Map` keyed by `recipient_id`, and a `Map` keeps the
 * LAST write for a key, so a newest-first list left the OLDEST message as
 * the thread's representative.
 */
function seedMessages(): StubbedMessage[] {
  return [
    {
      message_id: "m-new",
      kind: "dm",
      sender_id: PARENT_ID,
      recipient_id: ADMIN_USER_A.user_id,
      counterparty_id: PARENT_ID,
      body: NEWER_BODY,
      created_at: "2026-09-20T15:00:00Z",
      sent_at: "2026-09-20T15:00:00Z",
      is_broadcast: false,
      is_read: false,
    },
    {
      message_id: "m-old",
      kind: "dm",
      sender_id: PARENT_ID,
      recipient_id: ADMIN_USER_A.user_id,
      counterparty_id: PARENT_ID,
      body: OLDER_BODY,
      created_at: "2026-09-20T12:00:00Z",
      sent_at: "2026-09-20T12:00:00Z",
      is_broadcast: false,
      is_read: true,
    },
  ];
}

/**
 * Stub the whole admin messages surface against a mutable list, so a
 * mark-read genuinely persists across a reload the way `$addToSet` on
 * `read_by` does server-side.
 */
async function stubMessagesPage(page: Page): Promise<{ readCalls: string[] }> {
  const messages = seedMessages();
  const readCalls: string[] = [];

  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);

  // Catch-all FIRST: Playwright matches handlers LIFO, so the specific stubs
  // below win and anything this spec forgot answers `{}` instead of 500ing.
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
  // The admin shell polls the inbox badge on every page.
  await page.route("**/api/v2/admin/inbox/counts*", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/users*", (route) =>
    fulfillJson(route, {
      users: [
        {
          user_id: PARENT_ID,
          display_name: PARENT_NAME,
          email: "dana@example.com",
          roles: ["parent"],
          status: "active",
        },
      ],
    }),
  );

  await page.route("**/api/v2/admin/messages/*/read", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const match = /\/messages\/([^/]+)\/read/.exec(route.request().url());
    const messageId = match ? decodeURIComponent(match[1]) : "";
    readCalls.push(messageId);
    const target = messages.find((m) => m.message_id === messageId);
    if (target) target.is_read = true;
    return fulfillJson(route, { status: "ok" });
  });

  await page.route("**/api/v2/admin/messages", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { messages });
  });

  return { readCalls };
}

test.describe("admin direct messages (#864)", () => {
  test("thread row shows unread and the LATEST message, and opening clears it", async ({
    page,
  }) => {
    await page.setViewportSize(PHONE);
    const { readCalls } = await stubMessagesPage(page);

    await page.goto("/admin/messages");
    await expect(page.getByTestId("admin-messages")).toBeVisible();

    const row = page.getByTestId("dm-thread-row");
    await expect(row).toHaveCount(1);
    await expect(row.getByTestId("unread-dot")).toBeVisible();
    // The preview is the newest message, not the oldest one a last-write-wins
    // `Map` would have kept.
    await expect(row.getByTestId("dm-thread-preview")).toHaveText(NEWER_BODY);

    await row.click();

    // Only the unread message is marked; the already-read one is not re-sent.
    await expect.poll(() => readCalls).toEqual(["m-new"]);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);

    // Server-side read state persisted, and nothing re-fires on reload.
    await page.reload();
    await expect(page.getByTestId("dm-thread-row")).toBeVisible();
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);
    expect(readCalls).toEqual(["m-new"]);
  });

  test("on a phone the unread reply is above the broadcast composer, and the thread replaces the list", async ({
    page,
  }) => {
    await page.setViewportSize(PHONE);
    await stubMessagesPage(page);

    await page.goto("/admin/messages");

    const list = page.getByTestId("dm-thread-list");
    await expect(list).toBeVisible();

    // Acceptance: reachable without scrolling past the broadcast composer.
    const composer = page.getByLabel("Broadcast message body");
    const listBox = await list.boundingBox();
    const composerBox = await composer.boundingBox();
    expect(listBox).not.toBeNull();
    expect(composerBox).not.toBeNull();
    expect(listBox!.y).toBeLessThan(composerBox!.y);
    expect(listBox!.y).toBeLessThan(PHONE.height);

    // Opening a thread replaces the list, and Back brings it back.
    await page.getByTestId("dm-thread-row").click();
    await expect(page.getByTestId("dm-thread-panel")).toBeVisible();
    await expect(page.getByTestId("dm-list-panel")).toBeHidden();

    const back = page.getByTestId("dm-back");
    await expect(back).toBeVisible();
    await back.click();
    await expect(page.getByTestId("dm-list-panel")).toBeVisible();
    await expect(page.getByTestId("dm-thread-panel")).toHaveCount(0);
  });

  test("the ?dm= deep link marks the thread read too, not just a row click", async ({
    page,
  }) => {
    // The Payments buckets "Message" action lands here with the thread already
    // open and no click to hang a mark-read off. On desktop the list stays
    // beside the open thread, so an unmarked thread would show an unread dot
    // next to a conversation the admin is reading.
    await page.setViewportSize(DESKTOP);
    const { readCalls } = await stubMessagesPage(page);

    await page.goto(`/admin/messages?dm=${PARENT_ID}`);

    await expect(page.getByTestId("dm-thread-panel")).toBeVisible();
    await expect.poll(() => readCalls).toEqual(["m-new"]);
    await expect(page.getByTestId("unread-dot")).toHaveCount(0);

    // And it stays at one call — no loop from the refetch that follows.
    await page.waitForTimeout(500);
    expect(readCalls).toEqual(["m-new"]);
  });

  test("on desktop an open thread sits beside the list", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await stubMessagesPage(page);

    await page.goto("/admin/messages");
    await page.getByTestId("dm-thread-row").click();

    await expect(page.getByTestId("dm-list-panel")).toBeVisible();
    const thread = page.getByTestId("dm-thread-panel");
    await expect(thread).toBeVisible();
    await expect(thread.getByTestId("dm-thread-messages")).toContainText(NEWER_BODY);
    await expect(thread.getByTestId("dm-thread-messages")).toContainText(OLDER_BODY);

    const listBox = await page.getByTestId("dm-list-panel").boundingBox();
    const threadBox = await thread.boundingBox();
    expect(listBox!.x).toBeLessThan(threadBox!.x);
  });

  test("on desktop the open thread is readable and the composer stays in its card", async ({
    page,
  }) => {
    // #893: the DM card was one half of a two-column page AND split itself in
    // two again, so at 1280 the open thread sat at roughly a quarter of the
    // content width and the composer's Send button hung out of the card.
    await page.setViewportSize(DESKTOP);
    await stubMessagesPage(page);

    await page.goto("/admin/messages");
    await page.getByTestId("dm-thread-row").click();

    const thread = page.getByTestId("dm-thread-panel");
    await expect(thread).toBeVisible();
    const threadBox = await thread.boundingBox();
    expect(threadBox).not.toBeNull();
    expect(threadBox!.width).toBeGreaterThanOrEqual(560);

    // Composer and Send inside the thread pane, not past its right edge.
    const input = thread.getByLabel("DM message body");
    const send = thread.getByRole("button", { name: "Send", exact: true });
    const inputBox = await input.boundingBox();
    const sendBox = await send.boundingBox();
    const threadRight = threadBox!.x + threadBox!.width;
    expect(inputBox!.x + inputBox!.width).toBeLessThanOrEqual(threadRight + 1);
    expect(sendBox!.x + sendBox!.width).toBeLessThanOrEqual(threadRight + 1);

    // And nothing pushes the page itself sideways.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
