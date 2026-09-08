import { test, expect, type Page } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

/**
 * Month close (spec docs/superpowers/specs/2026-09-07-month-close-design.md §5).
 *
 * NOTE ON THE ROUTE STUB: the month-close URL is named in full. A `*` glob
 * stops at `/`, so `**\/api/v2/admin/reports*` would NOT match
 * `/admin/reports/month-close` — the lesson from the payments buckets spec,
 * where a `payments*` glob silently missed `/payments/collections`.
 */

const MONTH_CLOSE_URL = "**/api/v2/admin/reports/month-close*";

/** The period the page asks for by default is "this month"; the fixture is period-agnostic. */
function monthClose(overrides: Record<string, unknown> = {}) {
  return {
    generated_at: "2026-09-30T14:00:00Z",
    timezone: "America/Chicago",
    period: "2026-09",
    invoices: {
      generated: 42,
      emailed: 30,
      autopay_notices: 10,
      not_sent: 2,
      voided: 3,
      voided_cents: 36_000,
      void_reasons: [{ reason: "duplicate invoice", count: 3 }],
    },
    money: {
      billed_cents: 500_000,
      collected_cents: 400_000,
      outstanding_cents: 100_000,
      collection_rate: 0.8,
    },
    autopay_run: {
      charge_on: "2026-09-08",
      charge_on_varies: false,
      has_run: true,
      scheduled: { count: 10, cents: 120_000 },
      succeeded: { count: 8, cents: 96_000 },
      failed: { count: 2, cents: 24_000 },
      pending: { count: 0, cents: 0 },
    },
    odd: [
      {
        code: "autopay_no_card",
        label: "Autopay on with no card on file",
        count: 2,
        items: [
          {
            kind: "family",
            id: "par-1",
            label: "Dana Whitfield",
            href: "/admin/families/par-1",
          },
          {
            kind: "family",
            id: "par-2",
            label: "Mateo Ruiz",
            href: "/admin/families/par-2",
          },
        ],
      },
      { code: "invoice_without_enrollment", label: "Invoice without enrollment", count: 0, items: [] },
      { code: "paused_family_invoiced", label: "Paused family still invoiced", count: 0, items: [] },
      {
        code: "autopay_on_dead_enrollment",
        label: "Autopay on a cancelled or withdrawn enrollment",
        count: 0,
        items: [],
      },
    ],
    tuition_discounts: {
      gross_cents: 600_000,
      discount_cents: 100_000,
      net_cents: 500_000,
      by_category: [{ category: "scholarship", amount_cents: 100_000 }],
    },
    warnings: [],
    ...overrides,
  };
}

const AUGUST_CLOSE = monthClose({
  period: "2026-08",
  tuition_discounts: {
    gross_cents: 400_000,
    discount_cents: 20_000,
    net_cents: 380_000,
    by_category: [{ category: "coach_child", amount_cents: 20_000 }],
  },
});

async function stubMonthCloseShell(page: Page): Promise<void> {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  // Catch-all FIRST: Playwright matches handlers LIFO, so the specific stubs
  // below win and any endpoint this spec forgot answers `{}` instead of 500ing.
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [] }),
  );
  await page.route("**/api/v2/admin/finance/revenue*", (route) =>
    fulfillJson(route, { by_month: {} }),
  );
  await page.route("**/api/v2/admin/reports/dashboard*", (route) =>
    fulfillJson(route, REPORTS_DASHBOARD_EMPTY),
  );
  await page.route("**/api/v2/admin/reports/projected-income*", (route) =>
    fulfillJson(route, {
      period: "2026-10",
      total_cents: 0,
      autopay_cents: 0,
      manual_cents: 0,
      autopay_enrollment_count: 0,
      manual_enrollment_count: 0,
      by_session: [],
      empty: true,
    }),
  );
  await page.route("**/api/v2/admin/reports/enrollment-funnel*", (route) =>
    fulfillJson(route, {
      period: "2026-09",
      leads: 0,
      applied: 0,
      assessed: 0,
      confirmed: 0,
      enrolled: 0,
      conversion_rate: null,
      empty: true,
    }),
  );
  await page.route("**/api/v2/admin/reports/attendance-trends*", (route) =>
    fulfillJson(route, { periods: [], empty: true }),
  );
  await page.route("**/api/v2/admin/reports/coach-utilization*", (route) =>
    fulfillJson(route, { periods: [], coaches: [], empty: true }),
  );
}

const REPORTS_DASHBOARD_EMPTY = {
  period: "2026-09",
  billed_cents: 0,
  cash_collected_cents: 0,
  outstanding_dues_cents: 0,
  collection_rate: null,
  attendance: { present_count: 0, recorded_count: 0, attendance_rate: null, empty: true },
  sessions: {
    scheduled_count: 0,
    completed_count: 0,
    cancelled_count: 0,
    enrolled_seats: 0,
    capacity: 0,
    capacity_utilization: null,
    waitlist_count: 0,
    empty: true,
  },
  expenses: { total_cents: 0, by_category: [], empty: true },
  payroll: {
    estimated_cents: null,
    approved_cents: null,
    paid_cents: null,
    unpaid_cents: null,
    blocked_by: null,
    empty: true,
  },
  profit_and_loss: {
    revenue_cents: 0,
    coach_payroll_cents: null,
    rent_cents: 0,
    misc_expenses_cents: 0,
    net_profit_cents: null,
    profit_margin: null,
  },
  collections_risk: {
    overdue_family_count: 0,
    overdue_cents: 0,
    failed_payment_count: 0,
    partial_payment_count: 0,
    aging_buckets: [],
  },
  empty_states: [],
};

test.describe("admin month close", () => {
  test("six tiles, the odd box and the discount card render from one payload", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));

    await page.goto("/admin/reports");
    await expect(page.getByTestId("admin-month-close")).toBeVisible({ timeout: 45_000 });

    await expect(page.getByTestId("month-close-tile-generated-value")).toHaveText("42");
    // The sum is the true sent count; the split is in the hint.
    await expect(page.getByTestId("month-close-tile-emailed-value")).toHaveText("40");
    await expect(page.getByTestId("month-close-tile-emailed")).toContainText("30 invoice emails");
    await expect(page.getByTestId("month-close-tile-voided-value")).toHaveText("3");
    await expect(page.getByTestId("month-close-tile-billed-value")).toHaveText("$5,000.00");
    await expect(page.getByTestId("month-close-tile-collected-value")).toHaveText("$4,000.00");
    await expect(page.getByTestId("month-close-tile-collected")).toContainText(
      "80% of what was billed",
    );
    await expect(page.getByTestId("month-close-tile-outstanding-value")).toHaveText("$1,000.00");

    // "5 voided" is always explainable.
    await expect(page.getByTestId("void-reasons")).toContainText("duplicate invoice");

    // The tuition discount card moved off Dues.
    await expect(page.getByTestId("tuition-discounts-section")).toContainText("$6,000.00");
    await expect(page.getByTestId("tuition-discounts-row-scholarship")).toContainText("$1,000.00");

    // Removed with the redesign: the payments feed and the CSV export cards.
    await expect(page.getByTestId("recent-payments-card")).toHaveCount(0);
    await expect(page.getByTestId("failed-autopay-alert")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Export CSV" })).toHaveCount(0);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("the run box reports the outcome after the charge date and links to Payments", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));

    await page.goto("/admin/reports");
    await expect(page.getByTestId("autopay-run-box")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("autopay-run-headline")).toContainText("Ran Sep 8, 2026");
    await expect(page.getByTestId("autopay-run-succeeded")).toContainText("8 charges");
    await expect(page.getByTestId("autopay-run-failed")).toContainText("$240.00");
    await expect(page.getByTestId("autopay-run-failed-link")).toHaveAttribute(
      "href",
      "/admin/payments",
    );

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("before the charge date the run box shows only what is scheduled", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) =>
      fulfillJson(
        route,
        monthClose({
          autopay_run: {
            charge_on: "2026-09-08",
            charge_on_varies: true,
            has_run: false,
            scheduled: { count: 10, cents: 120_000 },
            succeeded: { count: 0, cents: 0 },
            failed: { count: 0, cents: 0 },
            pending: { count: 10, cents: 120_000 },
          },
        }),
      ),
    );

    await page.goto("/admin/reports");
    await expect(page.getByTestId("autopay-run-headline")).toContainText(
      "Runs on Sep 8, 2026 and later",
      { timeout: 45_000 },
    );
    await expect(page.getByTestId("autopay-run-pending")).toContainText("10 charges");
    await expect(page.getByTestId("autopay-run-succeeded")).toHaveCount(0);
    await expect(page.getByTestId("autopay-run-failed-link")).toHaveCount(0);

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("an odd row expands into links, and a warning is shown once", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) =>
      fulfillJson(route, monthClose({ warnings: ["attempts_unavailable"] })),
    );

    await page.goto("/admin/reports");
    await expect(page.getByTestId("anything-odd-box")).toBeVisible({ timeout: 45_000 });

    // Every check renders, even at zero, so the owner learns the box's shape.
    await expect(page.getByTestId("odd-invoice_without_enrollment-count")).toHaveText("0");
    await expect(page.getByTestId("odd-autopay_no_card-count")).toHaveText("2");

    await expect(page.getByTestId("odd-autopay_no_card-items")).toHaveCount(0);
    await page.getByTestId("odd-autopay_no_card").getByRole("button").click();
    const items = page.getByTestId("odd-autopay_no_card-items");
    await expect(items).toContainText("Dana Whitfield");
    await expect(items.getByRole("link", { name: "Dana Whitfield" })).toHaveAttribute(
      "href",
      "/admin/families/par-1",
    );

    await expect(page.getByTestId("month-close-warnings")).toContainText(
      "charge attempts could not be read",
    );

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("an empty month shows an em dash, not 0%", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) =>
      fulfillJson(
        route,
        monthClose({
          invoices: {
            generated: 0,
            emailed: 0,
            autopay_notices: 0,
            not_sent: 0,
            voided: 0,
            voided_cents: 0,
            void_reasons: [],
          },
          money: {
            billed_cents: 0,
            collected_cents: 0,
            outstanding_cents: 0,
            collection_rate: null,
          },
          odd: [],
        }),
      ),
    );

    await page.goto("/admin/reports");
    await expect(page.getByTestId("month-close-tile-collected")).toContainText(
      "— of what was billed",
      { timeout: 45_000 },
    );
    await expect(page.getByTestId("month-close-tile-voided")).toContainText("nothing voided");
    await expect(page.getByTestId("void-reasons")).toHaveCount(0);
    // All four checks still render at zero.
    await expect(page.getByTestId("odd-autopay_on_dead_enrollment-count")).toHaveText("0");

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("the period picker drives the discount card, and both exports fire", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const requestedPeriods: string[] = [];
    const exportedReports: string[] = [];
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => {
      const period = new URL(route.request().url()).searchParams.get("period") ?? "";
      requestedPeriods.push(period);
      return fulfillJson(route, period === "2026-08" ? AUGUST_CLOSE : monthClose());
    });
    await page.route("**/api/v2/admin/reports/*.csv*", (route) => {
      const name = new URL(route.request().url()).pathname.split("/").at(-1) ?? "";
      exportedReports.push(name.replace(/\.csv$/, ""));
      return route.fulfill({
        status: 200,
        contentType: "text/csv",
        body: "account,amount\nUndeposited Funds,100\n",
      });
    });

    await page.goto("/admin/reports");
    await expect(page.getByTestId("tuition-discounts-section")).toContainText("$6,000.00", {
      timeout: 45_000,
    });

    // One picker for the whole page: the discount card follows it rather than
    // carrying its own URL param the way the Dues page did.
    await page.getByTestId("month-close-period").fill("2026-08");
    await expect(page.getByTestId("tuition-discounts-section")).toContainText("$4,000.00");
    await expect(page.getByTestId("tuition-discounts-row-coach_child")).toBeVisible();
    expect(requestedPeriods).toContain("2026-08");

    await page.getByTestId("export-quickbooks").click();
    await expect.poll(() => exportedReports).toContain("quickbooks");
    await page.getByTestId("export-deposit-slip").click();
    await expect.poll(() => exportedReports).toContain("deposit-slip");

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
