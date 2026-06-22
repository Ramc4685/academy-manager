/**
 * Admin Billing Health page (#235).
 *
 * Verifies the three observability sections render from stubbed BFF data and
 * that the recovery actions (run reconciliation, retry charge, view attempts)
 * fire the expected v2 admin requests.
 */

import { test, expect, type Page, type Route } from "@playwright/test";

import {
  collectConsoleErrors,
  installTenantGuard,
} from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

const FAILED_ROW = {
  invoice_id: "inv-2026-06",
  parent_id: "parent-1",
  parent_name: "Sarah M.",
  period: "2026-06",
  total_cents: 12000,
  balance_due_cents: 12000,
  currency: "usd",
  latest_attempt_at: "2026-06-21T09:45:00Z",
  latest_decline_code: "card_declined",
  attempt_count: 2,
};

const QUARANTINED_EVENT = {
  event_id: "evt_1Abc123",
  event_type: "payment_intent.succeeded",
  status: "quarantined",
  object_id: "pi_1",
  object_type: "payment_intent",
  received_at: "2026-06-21T09:42:00Z",
  last_attempt_at: "2026-06-21T09:42:00Z",
  retry_count: 3,
  error_message: "parent mismatch: invoice=parent_A payment_intent=parent_B",
};

async function stubAdmin(page: Page): Promise<void> {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  // Catch-all admin BFF (registered first → lowest priority).
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
}

test.describe("admin billing health", () => {
  test("renders all three sections with stat counts", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    await stubAdmin(page);

    await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
      fulfillJson(route, {
        runs: [
          {
            run_id: "r-1",
            started_at: "2026-06-21T10:02:00Z",
            finished_at: "2026-06-21T10:02:01Z",
            scanned: 8,
            repaired: 0,
            skipped: 8,
            quarantined: 0,
            failed: 0,
            errors: [],
          },
        ],
      }),
    );
    await page.route("**/api/v2/admin/billing/failed-payment-attempts", (route) =>
      fulfillJson(route, { rows: [FAILED_ROW] }),
    );
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [QUARANTINED_EVENT] }),
    );

    await page.goto("/admin/billing-health");

    await expect(page.getByTestId("billing-health-page")).toBeVisible();
    await expect(page.getByTestId("reconciliation-runs-table")).toBeVisible();
    await expect(page.getByTestId("failed-payments-table")).toBeVisible();
    await expect(page.getByTestId("quarantined-events-table")).toBeVisible();
    await expect(page.getByText("Sarah M.")).toBeVisible();
    await expect(page.getByTestId("billing-health-status")).toContainText("Needs attention");

    expect(errors).toEqual([]);
    guard.assertNoLegacyApiCalls();
  });

  test("run reconciliation fires POST and shows the new run", async ({ page }) => {
    await stubAdmin(page);
    let reconciled = false;

    await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
      fulfillJson(route, {
        runs: reconciled
          ? [
              {
                run_id: "r-2",
                started_at: "2026-06-21T10:12:00Z",
                finished_at: "2026-06-21T10:12:01Z",
                scanned: 9,
                repaired: 1,
                skipped: 8,
                quarantined: 0,
                failed: 0,
                errors: [],
              },
            ]
          : [],
      }),
    );
    await page.route("**/api/v2/admin/billing/failed-payment-attempts", (route) =>
      fulfillJson(route, { rows: [] }),
    );
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [] }),
    );

    let postFired = false;
    await page.route("**/api/v2/admin/billing/reconcile-now", (route: Route) => {
      postFired = true;
      reconciled = true;
      return fulfillJson(route, {
        run_id: "r-2",
        scanned: 9,
        repaired: 1,
        skipped: 8,
        quarantined: 0,
        failed: 0,
        errors: [],
      });
    });

    await page.goto("/admin/billing-health");
    await page.getByTestId("run-reconciliation").click();

    await expect.poll(() => postFired).toBe(true);
    await expect(page.getByTestId("reconciliation-runs-table")).toContainText("9");
  });

  test("retry charges the invoice via autopay", async ({ page }) => {
    await stubAdmin(page);
    await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
      fulfillJson(route, { runs: [] }),
    );
    await page.route("**/api/v2/admin/billing/failed-payment-attempts", (route) =>
      fulfillJson(route, { rows: [FAILED_ROW] }),
    );
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [] }),
    );

    let chargeFired = false;
    await page.route(
      "**/api/v2/admin/billing/invoices/inv-2026-06/charge-autopay",
      (route: Route) => {
        chargeFired = true;
        return fulfillJson(route, {
          invoice_id: "inv-2026-06",
          success: true,
          status: "paid",
          balance_due_cents: 0,
          requires_action: false,
          decline_code: null,
        });
      },
    );

    await page.goto("/admin/billing-health");
    await page.getByTestId("retry-inv-2026-06").click();

    await expect.poll(() => chargeFired).toBe(true);
    await expect(page.getByTestId("failed-row-inv-2026-06")).toContainText(
      "Charged successfully",
    );
  });

  test("view opens the invoice attempt timeline", async ({ page }) => {
    await stubAdmin(page);
    await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
      fulfillJson(route, { runs: [] }),
    );
    await page.route("**/api/v2/admin/billing/failed-payment-attempts", (route) =>
      fulfillJson(route, { rows: [FAILED_ROW] }),
    );
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [] }),
    );
    await page.route(
      "**/api/v2/admin/billing/invoices/inv-2026-06/attempts",
      (route) =>
        fulfillJson(route, {
          attempts: [
            {
              attempt_id: "a-2",
              status: "failed",
              amount_cents: 12000,
              currency: "usd",
              stripe_payment_intent_id: "pi_3xyz",
              failure_code: "card_declined",
              failure_message: "Your card was declined.",
              created_at: "2026-06-21T09:45:00Z",
            },
          ],
        }),
    );

    await page.goto("/admin/billing-health");
    await page.getByTestId("view-inv-2026-06").click();

    await expect(page.getByTestId("attempts-timeline")).toBeVisible();
    await expect(page.getByText("Your card was declined.")).toBeVisible();
  });
});
