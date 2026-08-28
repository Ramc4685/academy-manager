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

const DUNNING_ROW = {
  invoice_id: "inv-dunned",
  parent_id: "parent-2",
  parent_name: "Ana P.",
  period: "2026-07",
  status: "dunned",
  attempt_count: 4,
  next_attempt_at: null,
  last_attempt_at: "2026-07-08T09:00:00Z",
  last_failure_code: "insufficient_funds",
  terminal_at: "2026-07-08T09:00:00Z",
  autopay_disable_status: "failed",
  autopay_disable_error: "transition rejected",
  autopay_disabled_at: null,
  balance_due_cents: 12000,
  currency: "usd",
};

const READY_CONNECT = {
  connected_account: {
    configured: true,
    status: "active",
    charges_enabled: true,
    payouts_enabled: true,
    ready_for_charges: true,
    account_id_masked: "acct...6f21",
  },
  allow_platform_charge_fallback: false,
  payments_possible: true,
  funds_route_to_academy: true,
  webhook_events: { quarantined: 1, failed: 0 },
};

async function stubConnectReadiness(page: Page, body: unknown): Promise<void> {
  await page.route("**/api/v2/admin/billing/connect-readiness", (route) =>
    fulfillJson(route, body),
  );
}

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
  // Healthy Connect readiness by default (#432). Must come after the
  // catch-all — later routes win — or the card would receive `{}` and the
  // page would crash on the missing connected_account. A test that needs a
  // different state registers its own route afterwards.
  await stubConnectReadiness(page, READY_CONNECT);
}

async function stubDunning(page: Page, rows: unknown[] = []): Promise<void> {
  await page.route("**/api/v2/admin/billing/dunning", (route) =>
    fulfillJson(route, { rows }),
  );
}

test.describe("admin billing health", () => {
  test("renders billing health sections with stat counts", async ({ page }) => {
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
    await stubDunning(page, [DUNNING_ROW]);

    await page.goto("/admin/billing-health");

    await expect(page.getByTestId("billing-health-page")).toBeVisible();
    await expect(page.getByTestId("reconciliation-runs-table")).toBeVisible();
    await expect(page.getByTestId("failed-payments-table")).toBeVisible();
    await expect(page.getByTestId("dunning-table")).toBeVisible();
    await expect(page.getByTestId("quarantined-events-table")).toBeVisible();
    await expect(page.getByText("Sarah M.")).toBeVisible();
    await expect(page.getByTestId("dunning-row-inv-dunned")).toContainText("Ana P.");
    await expect(page.getByTestId("dunning-row-inv-dunned")).toContainText(
      "Disable failed: transition rejected",
    );
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
    await stubDunning(page);

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
    await stubDunning(page);

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
    await stubDunning(page);
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
  test("payment readiness card shows a healthy connected account", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdmin(page);
    await stubDunning(page);

    await page.goto("/admin/billing-health");

    const card = page.getByTestId("payment-readiness");
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-tone", "green");
    await expect(card.getByText("Ready to take payments")).toBeVisible();
    await expect(card.getByText("acct...6f21")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("payment readiness card warns when parents cannot pay at all", async ({ page }) => {
    await stubAdmin(page);
    await stubDunning(page);
    await stubConnectReadiness(page, {
      connected_account: {
        configured: false,
        status: null,
        charges_enabled: false,
        payouts_enabled: false,
        ready_for_charges: false,
        account_id_masked: null,
      },
      allow_platform_charge_fallback: false,
      payments_possible: false,
      funds_route_to_academy: false,
      webhook_events: { quarantined: 0, failed: 0 },
    });

    await page.goto("/admin/billing-health");

    const card = page.getByTestId("payment-readiness");
    await expect(card).toHaveAttribute("data-tone", "red");
    await expect(card.getByText("Parents cannot pay right now")).toBeVisible();
  });

  test("payment readiness card flags money landing on the platform account", async ({
    page,
  }) => {
    await stubAdmin(page);
    await stubDunning(page);
    await stubConnectReadiness(page, {
      connected_account: {
        configured: true,
        status: "restricted",
        charges_enabled: false,
        payouts_enabled: false,
        ready_for_charges: false,
        account_id_masked: "acct...6f21",
      },
      allow_platform_charge_fallback: true,
      payments_possible: true,
      funds_route_to_academy: false,
      webhook_events: { quarantined: 0, failed: 2 },
    });

    await page.goto("/admin/billing-health");

    const card = page.getByTestId("payment-readiness");
    // Payments succeed, so this is not red — but the money is not the
    // academy's, so it must not read as healthy either.
    await expect(card).toHaveAttribute("data-tone", "amber");
    await expect(card.getByText(/landing on the platform account/)).toBeVisible();
  });

  test("stat tiles report real webhook counts, not a capped page length", async ({
    page,
  }) => {
    await stubAdmin(page);
    await stubDunning(page);
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [QUARANTINED_EVENT] }),
    );
    await stubConnectReadiness(page, {
      ...READY_CONNECT,
      webhook_events: { quarantined: 137, failed: 4 },
    });

    await page.goto("/admin/billing-health");

    // The list route returns one event; the count says 137. Before #432 the
    // tile counted that list and would have shown 1.
    await expect(page.getByText("137", { exact: true })).toBeVisible();
    await expect(page.getByText("Failed Events")).toBeVisible();
    await expect(page.getByTestId("payment-readiness")).toContainText(
      "137 quarantined · 4 failed",
    );
  });
});
