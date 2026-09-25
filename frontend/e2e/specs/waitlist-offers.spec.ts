/**
 * X2: waitlist seat offers, end to end at the BFF boundary.
 *
 * Before X2 the "a seat opened" email linked to /parent/requests, which had
 * no waitlist UI and nothing called the confirm route, so every offer expired
 * unclaimed. Admin views dropped `offered` rows as well. These specs pin:
 * the email link lands on the offer, confirm and decline reach the backend,
 * an expired or closed offer tells the family what happened, and admins see
 * the held seat and its deadline.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const OFFER_ID = "wl-offer-1";
const IN_TWO_DAYS = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000 + 5 * 60 * 1000).toISOString();

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function offerRow(overrides: Record<string, unknown> = {}) {
  return {
    waitlist_id: OFFER_ID,
    session_id: "sess-1",
    session_title: "Junior Beginners",
    schedule_label: "Thursdays 6:00 PM CDT",
    location: "Court 1",
    student_id: "st-1",
    student_name: "Ava Kim",
    status: "offered",
    joined_at: "2026-09-01T12:00:00Z",
    offer_expires_at: IN_TWO_DAYS,
    ...overrides,
  };
}

async function stubParent(page: Page, entries: unknown[]) {
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET"
      ? json(route, {
          user_id: "user-parent-e2e",
          email: "parent@example.com",
          academy_id: "academy-e2e",
          roles: ["parent"],
        })
      : route.fallback(),
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
    }),
  );
  await page.route("**/api/v2/parent/children", (route) => json(route, { children: [] }));
  await page.route("**/api/v2/parent/absences", (route) => json(route, { notices: [] }));
  let current = entries;
  await page.route("**/api/v2/parent/waitlist", (route) =>
    route.request().method() === "GET" ? json(route, { entries: current }) : route.fallback(),
  );
  return { setEntries: (next: unknown[]) => (current = next) };
}

test.describe("parent — waitlist seat offer", () => {
  test("the email link lands on the offer with a countdown, and Confirm enrolls", async ({
    page,
  }) => {
    const list = await stubParent(page, [offerRow()]);
    const confirmCalls: string[] = [];
    await page.route(`**/api/v2/parent/waitlist/${OFFER_ID}/confirm`, (route) => {
      confirmCalls.push(route.request().method());
      list.setEntries([]);
      return json(route, { waitlist_id: OFFER_ID, enrollment_id: "enr-new" });
    });

    await page.goto(`/parent/requests?offer=${OFFER_ID}`);

    const card = page.getByTestId(`waitlist-entry-${OFFER_ID}`);
    await expect(card).toBeVisible();
    await expect(card.getByText("SEAT OFFERED", { exact: true })).toBeVisible();
    await expect(card.getByTestId("waitlist-offer-countdown")).toHaveText(/^2 days/);

    await card.getByTestId("waitlist-offer-confirm").click();

    await expect(page.getByTestId("waitlist-offer-confirmed")).toContainText("The seat is yours");
    expect(confirmCalls).toEqual(["POST"]);
  });

  test("Decline asks first, then gives the seat back", async ({ page }) => {
    const list = await stubParent(page, [offerRow()]);
    const declineCalls: string[] = [];
    await page.route(`**/api/v2/parent/waitlist/${OFFER_ID}/decline`, (route) => {
      declineCalls.push(route.request().method());
      list.setEntries([]);
      return json(route, { waitlist_id: OFFER_ID, status: "removed" });
    });

    await page.goto(`/parent/requests?offer=${OFFER_ID}`);
    await page.getByTestId("waitlist-offer-decline").click();

    // Nothing is sent until the family confirms in the dialog.
    await expect(page.getByText("Decline this seat?")).toBeVisible();
    expect(declineCalls).toEqual([]);
    await page.getByTestId("waitlist-offer-decline-confirm").click();

    await expect(page.getByTestId(`waitlist-entry-${OFFER_ID}`)).toHaveCount(0);
    expect(declineCalls).toEqual(["POST"]);
  });

  test("an offer that expired before the click says the seat moved on", async ({ page }) => {
    await stubParent(page, [offerRow()]);
    await page.route(`**/api/v2/parent/waitlist/${OFFER_ID}/confirm`, (route) =>
      json(
        route,
        {
          error: {
            code: "Enrollment.WaitlistOfferExpired",
            message: `The offer on ${OFFER_ID} has expired`,
          },
        },
        409,
      ),
    );

    await page.goto(`/parent/requests?offer=${OFFER_ID}`);
    await page.getByTestId("waitlist-offer-confirm").click();

    await expect(page.getByTestId("waitlist-offer-error")).toContainText("next family");
  });

  test("an expired row explains itself and offers no buttons", async ({ page }) => {
    await stubParent(page, [
      offerRow({ status: "expired", offer_expires_at: "2026-09-20T12:00:00Z" }),
    ]);

    await page.goto(`/parent/requests?offer=${OFFER_ID}`);

    const card = page.getByTestId(`waitlist-entry-${OFFER_ID}`);
    await expect(card.getByText("EXPIRED", { exact: true })).toBeVisible();
    await expect(card.getByTestId("waitlist-offer-expired")).toContainText("next family");
    await expect(card.getByTestId("waitlist-offer-confirm")).toHaveCount(0);
  });

  test("a link to an offer that is no longer listed says so", async ({ page }) => {
    await stubParent(page, []);

    await page.goto(`/parent/requests?offer=${OFFER_ID}`);

    await expect(page.getByTestId("waitlist-offer-missing")).toContainText("no longer open");
  });
});

test.describe("admin — held seats are visible", () => {
  test("the Inbox waitlist shows the offered row and when it expires", async ({ page }) => {
    await page.route("**/api/v2/me", (route) =>
      json(route, {
        user_id: "admin-e2e",
        email: "admin@example.com",
        academy_id: "academy-e2e",
        roles: ["admin"],
      }),
    );
    await page.route("**/api/v2/me/memberships", (route) =>
      json(route, {
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
      json(route, { counts: { waitlist: 1 }, total: 1 }),
    );
    await page.route("**/api/v2/admin/messages*", (route) => json(route, { messages: [] }));
    await page.route("**/api/v2/admin/waitlist", (route) =>
      json(route, {
        total_waitlisted: 1,
        total_offered: 1,
        sessions: [
          {
            session_id: "sess-1",
            title: "Junior Beginners",
            location: "Court 1",
            start_at: "2026-10-01T23:00:00Z",
            capacity: 8,
            enrolled_count: 7,
            waitlist_count: 1,
            offered_count: 1,
            entries: [
              {
                waitlist_id: OFFER_ID,
                session_id: "sess-1",
                student_id: "st-1",
                parent_id: "par-1",
                parent_name: "Kim Family",
                full_name: "Ava Kim",
                status: "offered",
                position: 0,
                added_at: "2026-09-01T12:00:00Z",
                offer_expires_at: IN_TWO_DAYS,
              },
              {
                waitlist_id: "wl-waiting",
                session_id: "sess-1",
                student_id: "st-2",
                parent_id: "par-2",
                parent_name: "Lee Family",
                full_name: "Ben Lee",
                status: "waiting",
                position: 1,
                added_at: "2026-09-02T12:00:00Z",
                offer_expires_at: null,
              },
            ],
          },
        ],
      }),
    );

    await page.goto("/admin/inbox?tab=waitlist");

    const offered = page.getByTestId(`admin-waitlist-row-${OFFER_ID}`);
    await expect(offered).toBeVisible();
    await expect(offered.getByText("SEAT OFFERED", { exact: true })).toBeVisible();
    await expect(offered.getByText(/Held until/)).toBeVisible();
    await expect(page.getByText("1 seat offered")).toBeVisible();
    await expect(page.getByTestId("admin-waitlist-row-wl-waiting")).toBeVisible();
  });
});
