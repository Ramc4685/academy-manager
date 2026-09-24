import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Settings → Branding → Outbound email (roadmap L9a), against a mocked admin
 * BFF: the sender name + reply-to save as a PATCH of only the changed keys,
 * an unsafe sender name blocks Save with an inline error, and the hint shows
 * the display name families will see.
 */

const ADMIN_ME = {
  user_id: "user-admin-branding-e2e",
  email: "admin@alpha.example",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const ACADEMY = {
  academy_id: "academy-e2e",
  display_name: "Alpha Shuttle Club",
  timezone: "America/Chicago",
  contact_email: null,
  contact_phone: null,
  hours_text: null,
  address: null,
  logo_url: null,
  brand_color: null,
  currency: "USD",
  email_sender_name: null,
  email_reply_to: null,
};

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stub(page: Page): Promise<unknown[]> {
  const patches: unknown[] = [];
  let academy: Record<string, unknown> = { ...ACADEMY };
  // Catch-all first: the most recently registered route wins in Playwright.
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
          academy_name: "Alpha Shuttle Club",
          academy_slug: "academy-e2e",
          roles: ADMIN_ME.roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/academy", (route) => {
    const request = route.request();
    if (request.method() === "GET") return fulfillJson(route, academy);
    if (request.method() === "PATCH") {
      const body = request.postDataJSON() as Record<string, unknown>;
      patches.push(body);
      academy = { ...academy, ...body };
      return fulfillJson(route, academy);
    }
    return route.fallback();
  });
  return patches;
}

test.describe("admin settings → branding → outbound email", () => {
  test("saves sender name and reply-to as a PATCH of just those keys", async ({ page }) => {
    const patches = await stub(page);
    await page.goto("/admin/settings?panel=branding");
    const panel = page.getByTestId("admin-settings-branding");
    await expect(panel).toBeVisible();

    const name = panel.getByLabel("Sender name");
    // Wait for the server copy (placeholder = academy name) before editing.
    await expect(name).toHaveAttribute("placeholder", "Alpha Shuttle Club");
    await expect(panel.getByText('Families see email from "Alpha Shuttle Club"')).toBeVisible();

    await name.fill("Alpha Front Desk");
    await panel.getByLabel("Reply-to email").fill("desk@alpha.example");
    await expect(panel.getByText('Families see email from "Alpha Front Desk"')).toBeVisible();

    await panel.getByRole("button", { name: "Save branding" }).click();
    await expect(panel.getByText(/Saved at/)).toBeVisible();
    expect(patches).toEqual([
      { email_sender_name: "Alpha Front Desk", email_reply_to: "desk@alpha.example" },
    ]);
  });

  test("angle brackets in the sender name block Save with an inline error", async ({ page }) => {
    const patches = await stub(page);
    await page.goto("/admin/settings?panel=branding");
    const panel = page.getByTestId("admin-settings-branding");
    const name = panel.getByLabel("Sender name");
    await expect(name).toHaveAttribute("placeholder", "Alpha Shuttle Club");

    await name.fill("Alpha <spoof@example.com>");
    await expect(
      panel.getByText("Sender name cannot contain line breaks or angle brackets."),
    ).toBeVisible();
    await expect(name).toHaveAttribute("aria-invalid", "true");
    await expect(panel.getByRole("button", { name: "Save branding" })).toBeDisabled();
    expect(patches).toEqual([]);
  });
});
