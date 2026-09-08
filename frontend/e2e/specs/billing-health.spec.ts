/**
 * Admin Billing Health — the trimmed page (spec 2026-09-07).
 *
 * Four things and nothing else: the health verdict + Connect readiness,
 * quarantined webhooks with replay, reconciliation (runs, "Reconcile now", the
 * Stripe-id lookup, the autopay switch-off line) and link-a-charge.
 *
 * The failed-payments table, its Retry/View dialog and the dunning ladder are
 * gone — the Payments Failed-autopay bucket and the Family page own them — and
 * so is the legacy match queue. The page computes no verdict of its own.
 */

import { test, expect, type Page, type Route } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

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

const RUN = {
  run_id: "r-1",
  started_at: "2026-06-21T10:02:00Z",
  finished_at: "2026-06-21T10:02:01Z",
  scanned: 8,
  repaired: 0,
  skipped: 8,
  quarantined: 0,
  failed: 0,
  errors: [],
  notes: [],
};

const HEALTHY = {
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
  webhook_events: { quarantined: 0, failed: 0 },
  autopay_disable_failures: { count: 0, rows: [], truncated: false },
  health: { state: "ok", headline: "Stripe is healthy", reasons: [] },
};

async function stubConnectReadiness(page: Page, body: unknown): Promise<void> {
  await page.route("**/api/v2/admin/billing/connect-readiness", (route) =>
    fulfillJson(route, body),
  );
}

async function stubOwner(page: Page): Promise<void> {
  // ADMIN_USER_A carries `owner` (migration 0165 granted it to every existing
  // admin) — the page is owner-only since the trim.
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
  // Readiness is the one fatal read; the catch-all's `{}` would blank the
  // verdict. A test that needs another state registers its own route after.
  await stubConnectReadiness(page, HEALTHY);
  await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
    fulfillJson(route, { runs: [RUN] }),
  );
  await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
    fulfillJson(route, { events: [] }),
  );
}

test.describe("admin billing health", () => {
  test("shows the three tiles, the verdict and nothing about a family", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    await stubOwner(page);
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [QUARANTINED_EVENT] }),
    );

    await page.goto("/admin/billing-health");

    await expect(page.getByTestId("billing-health-page")).toBeVisible();
    // Tiles: Connect state, quarantined count, last reconciliation.
    await expect(page.getByText("Connect state", { exact: true })).toBeVisible();
    await expect(page.getByText("Quarantined events", { exact: true })).toBeVisible();
    await expect(page.getByText("Last reconciliation", { exact: true })).toBeVisible();
    await expect(page.getByTestId("reconciliation-runs-table")).toBeVisible();
    await expect(page.getByTestId("quarantined-events-table")).toBeVisible();
    await expect(page.getByTestId("reconciliation-lookup")).toBeVisible();
    await expect(page.getByTestId("link-charge-form")).toBeVisible();

    // Family payment behaviour lives on Payments and the Family page now.
    await expect(page.getByTestId("failed-payments-table")).toHaveCount(0);
    await expect(page.getByTestId("dunning-table")).toHaveCount(0);
    await expect(page.getByTestId("legacy-match-list")).toHaveCount(0);
    await expect(page.getByText("Open Failed Payments")).toHaveCount(0);
    await expect(page.getByText("Dunning Ladder")).toHaveCount(0);

    expect(errors).toEqual([]);
    guard.assertNoLegacyApiCalls();
  });

  test("the pill reads blocked when payments are impossible, even with an empty backlog", async ({
    page,
  }) => {
    // The contradiction this spec removes: nothing in the backlog, and no
    // parent can pay a cent. The old page called that "System healthy".
    await stubOwner(page);
    await stubConnectReadiness(page, {
      ...HEALTHY,
      connected_account: {
        configured: false,
        status: null,
        charges_enabled: false,
        payouts_enabled: false,
        ready_for_charges: false,
        account_id_masked: null,
      },
      payments_possible: false,
      funds_route_to_academy: false,
      health: {
        state: "blocked",
        headline: "Parents cannot pay right now",
        reasons: [
          {
            code: "connect_not_ready",
            detail: "No Stripe account is ready to take charges.",
          },
        ],
      },
    });

    await page.goto("/admin/billing-health");

    const pill = page.getByTestId("billing-health-status");
    await expect(pill).toHaveAttribute("data-state", "blocked");
    await expect(pill).toHaveAttribute("data-tone", "red");
    await expect(pill).toContainText("Parents cannot pay right now");
    await expect(page.getByTestId("payment-readiness")).toHaveAttribute("data-tone", "red");
    await expect(page.getByTestId("health-reasons")).toContainText(
      "No Stripe account is ready to take charges.",
    );
  });

  test("the pill renders the backend's attention headline", async ({ page }) => {
    await stubOwner(page);
    await stubConnectReadiness(page, {
      ...HEALTHY,
      webhook_events: { quarantined: 137, failed: 4 },
      health: {
        state: "attention",
        headline: "Payments work, 1 thing needs attention",
        reasons: [
          { code: "webhooks_quarantined", detail: "137 quarantined webhook events." },
        ],
      },
    });
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [QUARANTINED_EVENT] }),
    );

    await page.goto("/admin/billing-health");

    const pill = page.getByTestId("billing-health-status");
    await expect(pill).toHaveAttribute("data-state", "attention");
    await expect(pill).toHaveAttribute("data-tone", "amber");
    await expect(pill).toContainText("Payments work, 1 thing needs attention");
    // The tile shows the true aggregate, not the length of the capped list.
    await expect(page.getByText("137", { exact: true })).toBeVisible();
    await expect(page.getByTestId("webhook-truncation")).toContainText(
      "Showing the 1 most recent of 137 quarantined events.",
    );
  });

  test("readiness failing shows a retry panel, not a pill", async ({ page }) => {
    await stubOwner(page);
    await page.route("**/api/v2/admin/billing/connect-readiness", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "readiness check failed" }),
      }),
    );

    await page.goto("/admin/billing-health");

    // A 5xx is retried with backoff by the shared query client, so give the
    // fatal panel room to appear after the retries are exhausted.
    await expect(page.getByTestId("billing-health-fatal")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("retry-readiness")).toBeVisible();
    await expect(page.getByTestId("billing-health-status")).toHaveCount(0);
  });

  test("replay fires the POST for the quarantined event", async ({ page }) => {
    await stubOwner(page);
    await page.route("**/api/v2/admin/billing/webhooks**", (route) =>
      fulfillJson(route, { events: [QUARANTINED_EVENT] }),
    );

    let replayed: string | null = null;
    await page.route(
      "**/api/v2/admin/billing/webhook-events/evt_1Abc123/replay",
      (route: Route) => {
        replayed = "evt_1Abc123";
        return fulfillJson(route, { replayed: true, event_id: "evt_1Abc123" });
      },
    );

    await page.goto("/admin/billing-health");
    await page.getByTestId("replay-evt_1Abc123").click();

    await expect.poll(() => replayed).toBe("evt_1Abc123");
    await expect(page.getByTestId("quarantined-row-evt_1Abc123")).toContainText(
      "Replayed — processing",
    );
  });

  test("reconcile now fires POST and shows the new run", async ({ page }) => {
    await stubOwner(page);
    let reconciled = false;
    await page.route("**/api/v2/admin/billing/reconciliation-runs", (route) =>
      fulfillJson(route, {
        runs: reconciled ? [{ ...RUN, run_id: "r-2", scanned: 9, repaired: 1 }] : [],
      }),
    );

    let postFired = false;
    await page.route("**/api/v2/admin/billing/reconcile-now", (route: Route) => {
      postFired = true;
      reconciled = true;
      return fulfillJson(route, { ...RUN, run_id: "r-2", scanned: 9, repaired: 1 });
    });

    await page.goto("/admin/billing-health");
    await page.getByTestId("run-reconciliation").click();

    await expect.poll(() => postFired).toBe(true);
    await expect(page.getByTestId("reconciliation-runs-table")).toContainText("9");
  });

  test("reconcile now surfaces the unconfigured-Stripe message", async ({ page }) => {
    await stubOwner(page);
    await page.route("**/api/v2/admin/billing/reconcile-now", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Stripe reconciliation not configured" }),
      }),
    );

    await page.goto("/admin/billing-health");
    await page.getByTestId("run-reconciliation").click();

    // The inline alert; the global mutation toast repeats it.
    await expect(page.getByText(/Stripe reconciliation not configured/).first()).toBeVisible();
  });

  test("the reconciliation lookup lives here now", async ({ page }) => {
    await stubOwner(page);
    let queried: string | null = null;
    await page.route("**/api/v2/admin/billing/reconciliation?**", (route: Route) => {
      queried = route.request().url();
      return fulfillJson(route, {
        result: "MISSING_ALLOCATION",
        stripe_invoice_id: null,
        payment_intent_id: "pi_test_1",
        stripe_customer_id: "cus_1",
        local_invoice_id: "inv-open",
        ledger_payment_id: "lp_1",
        payment_allocation_id: null,
        checked_at: "2026-06-02T12:05:00Z",
        mismatches: [
          {
            code: "MISSING_ALLOCATION",
            message: "Ledger payment exists without payment allocation.",
            stripe_value: "paid",
            local_value: null,
          },
        ],
        manual_review_candidates: [],
      });
    });

    await page.goto("/admin/billing-health");
    await page.getByPlaceholder("pi_...").first().fill("pi_test_1");
    await page.getByRole("button", { name: "Run report" }).click();

    await expect.poll(() => queried).toContain("payment_intent_id=pi_test_1");
    await expect(page.getByText("Ledger payment exists without payment allocation.")).toBeVisible();
  });

  test("link a charge confirms first, then posts the right body", async ({ page }) => {
    await stubOwner(page);
    let posted: Record<string, unknown> | null = null;
    await page.route("**/api/v2/admin/billing/legacy-match/confirm", (route: Route) => {
      posted = route.request().postDataJSON();
      return fulfillJson(route, {
        invoice_id: "inv-legacy-1",
        payment_id: "legacy-match-ch_1",
        invoice_status: "paid",
        balance_due_cents: 0,
      });
    });

    await page.goto("/admin/billing-health");
    await page.getByTestId("link-invoice-id").fill("inv-legacy-1");
    await page.getByTestId("link-charge-id").fill("ch_1");
    await page.getByTestId("link-amount").fill("70.00");
    await page.getByTestId("link-charge-submit").click();

    // Nothing is posted until the confirmation naming the invoice and amount.
    const confirmation = page.getByTestId("link-charge-confirm");
    await expect(confirmation).toContainText("$70.00");
    await expect(confirmation).toContainText("inv-legacy-1");
    expect(posted).toBeNull();

    await page.getByTestId("link-charge-confirm-submit").click();

    await expect.poll(() => posted).not.toBeNull();
    expect(posted).toMatchObject({
      invoice_id: "inv-legacy-1",
      stripe_charge_id: "ch_1",
      amount_cents: 7000,
    });
    await expect(page.getByTestId("link-charge-success")).toContainText("paid");
  });

  test("link a charge renders a refusal inline", async ({ page }) => {
    await stubOwner(page);
    await page.route("**/api/v2/admin/billing/legacy-match/confirm", (route) =>
      route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "amount_cents 9000 exceeds balance_due_cents 7000",
        }),
      }),
    );

    await page.goto("/admin/billing-health");
    await page.getByTestId("link-invoice-id").fill("inv-legacy-1");
    await page.getByTestId("link-charge-id").fill("ch_1");
    await page.getByTestId("link-amount").fill("90.00");
    await page.getByTestId("link-charge-submit").click();
    await page.getByTestId("link-charge-confirm-submit").click();

    await expect(page.getByTestId("link-error")).toContainText("exceeds");
  });

  test("the autopay switch-off failures get their only surface", async ({ page }) => {
    await stubOwner(page);
    await stubConnectReadiness(page, {
      ...HEALTHY,
      autopay_disable_failures: {
        count: 2,
        rows: [
          {
            invoice_id: "inv-stuck",
            parent_id: "parent-9",
            error: "rate_limited",
            failed_at: "2026-09-07T09:00:00Z",
          },
        ],
        truncated: true,
      },
      health: {
        state: "attention",
        headline: "Payments work, 1 thing needs attention",
        reasons: [
          {
            code: "autopay_disable_failed",
            detail: "Autopay switch-off failed for 2 invoices.",
          },
        ],
      },
    });

    await page.goto("/admin/billing-health");

    const line = page.getByTestId("autopay-switch-off-failures");
    await expect(line).toContainText("Autopay switch-off failed for 2 invoices");
    await expect(line).toContainText("rate_limited");
    // Each invoice links to the family page, which owns the rest of the story.
    await expect(page.getByTestId("switch-off-inv-stuck")).toHaveAttribute(
      "href",
      "/admin/families/parent-9",
    );
  });

  test("payment readiness still flags money landing on the platform account", async ({
    page,
  }) => {
    await stubOwner(page);
    await stubConnectReadiness(page, {
      ...HEALTHY,
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
      health: {
        state: "ok",
        headline: "Stripe is healthy",
        // fallback_only is informational: it never raises the state.
        reasons: [{ code: "fallback_only", detail: "Charges land on the platform account." }],
      },
    });

    await page.goto("/admin/billing-health");

    const card = page.getByTestId("payment-readiness");
    await expect(card).toHaveAttribute("data-tone", "amber");
    await expect(card.getByText(/landing on the platform account/)).toBeVisible();
    // Payments succeed, so the verdict is still ok — the card carries the nuance.
    await expect(page.getByTestId("billing-health-status")).toHaveAttribute("data-state", "ok");
  });
});
