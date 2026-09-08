import { expect, test, type Page, type Route } from "@playwright/test";

import { billingRulesFixture } from "../fixtures/billing-rules";

/**
 * Settings → Billing rules (spec 2026-09-07-billing-rules-design).
 *
 * Covers the four boxes, fixed rows having no inputs, the late-fee note,
 * saving only the changed fields, an inline bound violation, the retired
 * `?panel=fees` deep link, and the owner-only gate.
 */

const OWNER_ME = {
  user_id: "user-owner-billing-rules-e2e",
  email: "owner@example.com",
  academy_id: "academy-e2e",
  roles: ["admin", "owner"],
};

const ADMIN_ONLY_ME = { ...OWNER_ME, user_id: "user-admin-only", roles: ["admin"] };

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubShell(page: Page, me: typeof OWNER_ME) {
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, me) : route.fallback(),
  );
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "BLNO Badminton Academy",
          academy_slug: "academy-e2e",
          roles: me.roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/academy", (route) =>
    route.request().method() === "GET"
      ? fulfillJson(route, {
          academy_id: "academy-e2e",
          display_name: "BLNO Badminton Academy",
          timezone: "America/Chicago",
          contact_email: null,
          contact_phone: null,
          hours_text: null,
          address: null,
          logo_url: null,
          brand_color: null,
        })
      : route.fallback(),
  );
}

/** Returns a getter for the last PUT body seen on /admin/billing/rules. */
function stubBillingRules(page: Page, opts: { error?: { status: number; body: unknown } } = {}) {
  const seen: { put: unknown } = { put: null };
  void page.route("**/api/v2/admin/billing/rules", (route) => {
    const request = route.request();
    if (request.method() === "GET") return fulfillJson(route, billingRulesFixture());
    if (request.method() === "PUT") {
      seen.put = request.postDataJSON();
      if (opts.error) return fulfillJson(route, opts.error.body, opts.error.status);
      const body = request.postDataJSON() as Record<string, number>;
      return fulfillJson(route, billingRulesFixture(body));
    }
    return route.fallback();
  });
  return seen;
}

test.describe("admin settings → billing rules", () => {
  test("the four boxes render, fixed rows are not inputs, and the note sits above the fees", async ({
    page,
  }) => {
    await stubShell(page, OWNER_ME);
    stubBillingRules(page);
    await page.goto("/admin/settings?panel=billing-rules");

    await expect(page.getByTestId("admin-settings-billing-rules")).toBeVisible();
    for (const key of [
      "monthly_invoicing",
      "late_payments",
      "leaving_and_pausing",
      "parent_messages",
    ]) {
      await expect(page.getByTestId(`billing-rules-group-${key}`)).toBeVisible();
    }

    // Fixed rows state a value with no box and no cursor.
    const retry = page.getByTestId("billing-rules-fixed-retry_schedule");
    await expect(retry).toContainText("same day, then 3, 5 and 7 days later");
    await expect(retry.locator("input")).toHaveCount(0);
    await expect(page.getByTestId("billing-rules-fixed-cancel_mid_month")).toContainText(
      "Full month owed, no refund",
    );
    await expect(page.getByTestId("billing-rules-fixed-autopay_charge_time")).toContainText(
      "09:00 academy time on the due date",
    );

    // The honest caveat, above the two late-fee inputs.
    const note = page.getByTestId("billing-rules-note-late_payments");
    await expect(note).toContainText("Not applied automatically yet");
    const noteBox = await note.boundingBox();
    const inputBox = await page.getByTestId("billing-rules-input-late_fee_cents").boundingBox();
    expect(noteBox && inputBox && noteBox.y < inputBox.y).toBe(true);
  });

  test("saving posts only the changed fields", async ({ page }) => {
    await stubShell(page, OWNER_ME);
    const seen = stubBillingRules(page);
    await page.goto("/admin/settings?panel=billing-rules");

    await expect(page.getByTestId("billing-rules-input-late_fee_cents")).toHaveValue("15.00");
    await expect(page.getByTestId("billing-rules-save")).toBeDisabled();

    await page.getByTestId("billing-rules-input-late_fee_cents").fill("17.50");
    await expect(page.getByTestId("billing-rules-save")).toContainText("Save Late fee");
    await page.getByTestId("billing-rules-save").click();

    await expect.poll(() => seen.put).toEqual({ late_fee_cents: 1750 });
    await expect(page.getByTestId("billing-rules-saved")).toBeVisible();
  });

  test("a bound violation renders inline against the offending field", async ({ page }) => {
    await stubShell(page, OWNER_ME);
    stubBillingRules(page);
    await page.goto("/admin/settings?panel=billing-rules");

    await page.getByTestId("billing-rules-input-billing_day").fill("31");

    await expect(page.getByTestId("billing-rules-error-billing_day")).toContainText(
      "between 1 and 28",
    );
    await expect(page.getByTestId("billing-rules-save")).toBeDisabled();
  });

  test("a server-side bound violation lands on the same field", async ({ page }) => {
    await stubShell(page, OWNER_ME);
    stubBillingRules(page, {
      error: {
        status: 422,
        body: { detail: { field: "late_fee_cents", message: "late_fee_cents must be between 0 and 100000" } },
      },
    });
    await page.goto("/admin/settings?panel=billing-rules");

    await page.getByTestId("billing-rules-input-late_fee_cents").fill("17.50");
    await page.getByTestId("billing-rules-save").click();

    await expect(page.getByTestId("billing-rules-error-late_fee_cents")).toContainText(
      "must be between 0 and 100000",
    );
  });

  test("?panel=fees still lands on Billing rules", async ({ page }) => {
    await stubShell(page, OWNER_ME);
    stubBillingRules(page);
    await page.goto("/admin/settings?panel=fees");

    await expect(page.getByTestId("admin-settings-billing-rules")).toBeVisible();
    await expect(page).toHaveURL(/\/admin\/settings\?panel=billing-rules$/);
  });

  test("an admin without the owner scope gets the owner-only panel", async ({ page }) => {
    await stubShell(page, ADMIN_ONLY_ME);
    stubBillingRules(page);
    await page.goto("/admin/settings?panel=billing-rules");

    await expect(page.getByTestId("owner-only-panel")).toBeVisible();
    await expect(page.getByTestId("admin-settings-billing-rules")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Billing rules", exact: true })).toHaveCount(0);
  });
});
