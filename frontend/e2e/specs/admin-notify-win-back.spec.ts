import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Settings → Notify: the per-academy win-back switch (hardcoded-values row
 * 10), against a mocked admin BFF. A never-saved setting reads as on (so an
 * academy like BLNO keeps its win-back emails), and turning it off sends only
 * that key.
 */

const ADMIN_ME = {
  user_id: "user-admin-notify-e2e",
  email: "admin@riverside.example",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stub(page: Page): Promise<unknown[]> {
  const patches: unknown[] = [];
  // The GET response omits win_back_enabled, as an academy that never saved it.
  let notifications: Record<string, unknown> = {
    daily_digest_to_admin: false,
    coach_digest_enabled: false,
    coach_digest_hour: 6,
    parent_digest_enabled: false,
    parent_digest_hour: 6,
  };

  // Catch-all first: Playwright matches the most recently registered route
  // first, so the specific stubs below win and shell polls get an empty shape.
  await page.route("**/api/v2/admin/**", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, {}) : route.fallback(),
  );
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, ADMIN_ME) : route.fallback(),
  );
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Riverside Shuttle Club",
          academy_slug: "academy-e2e",
          roles: ADMIN_ME.roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/academy/notifications", (route) => {
    const request = route.request();
    if (request.method() === "GET") return fulfillJson(route, notifications);
    if (request.method() === "PATCH") {
      const body = request.postDataJSON() as Record<string, unknown>;
      patches.push(body);
      notifications = { ...notifications, ...body };
      return fulfillJson(route, { win_back_enabled: true, ...notifications });
    }
    return route.fallback();
  });
  await page.route("**/api/v2/admin/comms/digests/log**", (route) =>
    fulfillJson(route, { entries: [] }),
  );
  return patches;
}

test.describe("admin notify win-back switch", () => {
  test("defaults on and saves only the switch when turned off", async ({ page }) => {
    const patches = await stub(page);
    await page.goto("/admin/settings?panel=notify");

    const toggle = page.getByTestId("notify-win-back-enabled");
    await expect(toggle).toBeChecked();

    await toggle.uncheck();
    await page.getByRole("button", { name: "Save changes" }).click();

    await expect.poll(() => patches).toEqual([{ win_back_enabled: false }]);
    await expect(toggle).not.toBeChecked();
  });
});
