import { test, expect, type Page } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import { openMonthCloseSection } from "../helpers/month-close-sections";
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

    // #862: the money figures lead; the invoice-run counts live in Invoices.
    await openMonthCloseSection(page, "invoices");
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
    await openMonthCloseSection(page, "discounts");
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
    await openMonthCloseSection(page, "autopay-run");
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
    await openMonthCloseSection(page, "autopay-run");
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
    await openMonthCloseSection(page, "invoices");
    await expect(page.getByTestId("month-close-tile-voided")).toContainText("nothing voided");
    await expect(page.getByTestId("void-reasons")).toHaveCount(0);
    // All four checks still render at zero.
    await expect(page.getByTestId("odd-autopay_on_dead_enrollment-count")).toHaveText("0");

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  // ------------------------------------------------------- verdict (#862)

  test("the page leads with a verdict that counts the month's real problems", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    // The fixture carries 2 autopay-no-card families, 2 failed charges and 2
    // invoices never sent.
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));

    await page.goto("/admin/reports");
    const verdict = page.getByTestId("month-close-verdict");
    await expect(verdict).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("month-close-verdict-headline")).toHaveText(
      "6 things need attention",
    );
    const issues = page.getByTestId("month-close-verdict-issues");
    await expect(issues).toContainText("Autopay on with no card on file: 2");
    await expect(issues).toContainText("Failed autopay charges: 2");
    await expect(issues).toContainText("Invoices not sent: 2");

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("a clean month says so, in one line", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) =>
      fulfillJson(
        route,
        monthClose({
          invoices: {
            generated: 42,
            emailed: 42,
            autopay_notices: 0,
            not_sent: 0,
            voided: 0,
            voided_cents: 0,
            void_reasons: [],
          },
          autopay_run: {
            charge_on: "2026-09-08",
            charge_on_varies: false,
            has_run: true,
            scheduled: { count: 10, cents: 120_000 },
            succeeded: { count: 10, cents: 120_000 },
            failed: { count: 0, cents: 0 },
            pending: { count: 0, cents: 0 },
          },
          odd: [],
        }),
      ),
    );

    await page.goto("/admin/reports");
    await expect(page.getByTestId("month-close-verdict-headline")).toHaveText(
      "Sep 2026 is ready to close",
      { timeout: 45_000 },
    );
    await expect(page.getByTestId("month-close-verdict-issues")).toHaveCount(0);

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("a failed month-close load never reads as ready to close (#837)", async ({ page }) => {
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/admin/reports");
    await expect(page.getByTestId("admin-reports-month-close-error")).toBeVisible({
      timeout: 45_000,
    });
    // The normalizer zero-fills an absent payload; zero issues must not become
    // a clean bill of health.
    await expect(page.getByTestId("month-close-verdict-headline")).toHaveText("—");
    await expect(page.getByTestId("month-close-verdict-issues")).toHaveCount(0);
  });

  test("the card wall collapses on a phone and opens on a desktop", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));

    // 400px is the width the design critique measured the 8,950px wall at.
    await page.setViewportSize({ width: 400, height: 800 });
    await page.goto("/admin/reports");
    await expect(page.getByTestId("month-close-verdict")).toBeVisible({ timeout: 45_000 });

    const groups = ["invoices", "autopay-run", "discounts", "analytics", "report-links"];
    for (const id of groups) {
      await expect(page.getByTestId(`month-close-section-${id}-toggle`)).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      await expect(page.getByTestId(`month-close-section-${id}-body`)).not.toBeVisible();
    }

    // The verdict and the three money figures are the first screen.
    const verdictBox = await page.getByTestId("month-close-verdict").boundingBox();
    expect(verdictBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(800);
    await expect(page.getByTestId("month-close-tile-billed-value")).toBeVisible();
    await expect(page.getByTestId("month-close-tile-outstanding-value")).toBeVisible();

    // Acceptance: at least half the 8,950px wall is gone with groups closed.
    const collapsedHeight = await page.evaluate(() => document.body.scrollHeight);
    expect(collapsedHeight).toBeLessThan(4_475);

    // Opening a group is what brings its cards back.
    await openMonthCloseSection(page, "discounts");
    await expect(page.getByTestId("tuition-discounts-section")).toBeVisible();

    // The same page on a desktop viewport opens every group by default.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.reload();
    await expect(page.getByTestId("month-close-verdict")).toBeVisible({ timeout: 45_000 });
    for (const id of groups) {
      await expect(page.getByTestId(`month-close-section-${id}-toggle`)).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    }
    await expect(page.getByTestId("autopay-run-box")).toBeVisible();

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
    await openMonthCloseSection(page, "discounts");
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

/**
 * People reports (roadmap L5a): the two cards in the "People" group. Both are
 * plain tables with text for every number, and each has an empty state. The
 * money card disappears for a role the money seam refuses (403).
 */
const MONEY_OWED_URL = "**/api/v2/admin/reports/people/money-owed-by-age*";
const INQUIRY_URL = "**/api/v2/admin/reports/people/inquiry-conversion*";

const MONEY_OWED = {
  as_of: "2026-09-23",
  generated_at: "2026-09-23T15:00:00Z",
  not_yet_due: {
    key: "not_yet_due",
    label: "Not yet due",
    min_days: null,
    max_days: 0,
    family_count: 2,
    total_cents: 6_000,
  },
  bands: [
    { key: "days_1_30", label: "1 to 30 days late", min_days: 1, max_days: 30, family_count: 1, total_cents: 3_500 },
    { key: "days_31_60", label: "31 to 60 days late", min_days: 31, max_days: 60, family_count: 1, total_cents: 7_000 },
    { key: "days_over_60", label: "Over 60 days late", min_days: 61, max_days: null, family_count: 1, total_cents: 4_000 },
  ],
  overdue_cents: 14_500,
  overdue_family_count: 2,
  balance_cents: 20_500,
  owing_family_count: 2,
};

function inquiryRow(source: string, lead: number, trial: number, enrolled: number) {
  const inquiries = lead + trial + enrolled;
  return {
    source,
    inquiries,
    lead,
    trial,
    enrolled,
    conversion_rate: inquiries ? enrolled / inquiries : null,
  };
}

const INQUIRIES = {
  date_from: "2026-06-26",
  date_to: "2026-09-23",
  timezone: "America/Chicago",
  sources: [
    inquiryRow("website", 1, 1, 1),
    inquiryRow("whatsapp_or_phone", 0, 1, 0),
    inquiryRow("referral", 1, 0, 1),
    inquiryRow("other", 0, 0, 0),
  ],
  total: inquiryRow("all", 2, 2, 2),
};

test.describe("admin reports: people", () => {
  test("money owed by age and inquiries by source render as tables", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));
    await page.route(MONEY_OWED_URL, (route) => fulfillJson(route, MONEY_OWED));
    const inquiryRanges: string[] = [];
    await page.route(INQUIRY_URL, (route) => {
      inquiryRanges.push(new URL(route.request().url()).search);
      return fulfillJson(route, INQUIRIES);
    });

    await page.goto("/admin/reports");
    await openMonthCloseSection(page, "people");

    const money = page.getByTestId("people-report-money-owed-table");
    await expect(money).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("people-report-money-owed-row-days_1_30")).toContainText(
      "1 to 30 days late",
    );
    await expect(page.getByTestId("people-report-money-owed-row-days_1_30")).toContainText(
      "$35.00",
    );
    await expect(page.getByTestId("people-report-money-owed-row-days_31_60")).toContainText(
      "$70.00",
    );
    await expect(page.getByTestId("people-report-money-owed-row-days_over_60")).toContainText(
      "1 family",
    );
    await expect(page.getByTestId("people-report-money-owed-total")).toContainText("$205.00");
    await expect(page.getByTestId("people-report-money-owed-total")).toContainText("2 families");
    await expect(money.getByRole("columnheader", { name: "Amount" })).toBeVisible();

    const inquiries = page.getByTestId("people-report-inquiries-table");
    await expect(inquiries).toBeVisible();
    await expect(page.getByTestId("people-report-inquiries-row-website")).toContainText(
      "Website form",
    );
    await expect(page.getByTestId("people-report-inquiries-row-website")).toContainText("33%");
    await expect(page.getByTestId("people-report-inquiries-row-referral")).toContainText("50%");
    await expect(page.getByTestId("people-report-inquiries-total")).toContainText("6");
    expect(inquiryRanges[0]).toBe("");

    // A picked range is sent as from/to.
    await page.getByTestId("people-report-inquiries-from").fill("2026-09-01");
    await expect.poll(() => inquiryRanges.some((q) => q.includes("from=2026-09-01"))).toBe(true);

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("the money card hides on 403 and both cards have empty states", async ({ page }) => {
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));
    await page.route(MONEY_OWED_URL, (route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Family money is not visible to your role" }),
      }),
    );
    await page.route(INQUIRY_URL, (route) =>
      fulfillJson(route, {
        ...INQUIRIES,
        sources: INQUIRIES.sources.map((row) => inquiryRow(row.source, 0, 0, 0)),
        total: inquiryRow("all", 0, 0, 0),
      }),
    );

    await page.goto("/admin/reports");
    await openMonthCloseSection(page, "people");
    await expect(page.getByTestId("people-report-inquiries-empty")).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByTestId("people-report-money-owed")).toHaveCount(0);
  });

  test("a family index with nobody owing shows the money empty state", async ({ page }) => {
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));
    await page.route(MONEY_OWED_URL, (route) =>
      fulfillJson(route, {
        ...MONEY_OWED,
        not_yet_due: { ...MONEY_OWED.not_yet_due, family_count: 0, total_cents: 0 },
        bands: MONEY_OWED.bands.map((band) => ({ ...band, family_count: 0, total_cents: 0 })),
        overdue_cents: 0,
        overdue_family_count: 0,
        balance_cents: 0,
        owing_family_count: 0,
      }),
    );
    await page.route(INQUIRY_URL, (route) => fulfillJson(route, INQUIRIES));

    await page.goto("/admin/reports");
    await openMonthCloseSection(page, "people");
    await expect(page.getByTestId("people-report-money-owed-empty")).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByTestId("people-report-money-owed-table")).toHaveCount(0);
  });
});

/**
 * People reports (roadmap L5b): attendance risk by class and coach, and
 * families lost and why. Both carry no money, so they render for any admin.
 */
const ATTENDANCE_RISK_URL = "**/api/v2/admin/reports/people/attendance-risk*";
const FAMILIES_LOST_URL = "**/api/v2/admin/reports/people/families-lost*";

const ATTENDANCE_RISK = {
  generated_at: "2026-09-23T15:00:00Z",
  by_class: [
    {
      session_id: "sess-sat",
      title: "Saturday Squad",
      coach_id: "coach-1",
      coach_name: "Testcoach One",
      students: 3,
      at_risk: 2,
      at_risk_rate: 2 / 3,
    },
    {
      session_id: "sess-new",
      title: "Brand New Class",
      coach_id: null,
      coach_name: null,
      students: 1,
      at_risk: 0,
      at_risk_rate: 0,
    },
  ],
  by_coach: [
    { coach_id: "coach-1", coach_name: "Testcoach One", classes: 1, students: 3, at_risk: 2, at_risk_rate: 2 / 3 },
    { coach_id: null, coach_name: null, classes: 1, students: 1, at_risk: 0, at_risk_rate: 0 },
  ],
  students: 4,
  at_risk: 2,
};

const FAMILIES_LOST = {
  date_from: "2026-06-26",
  date_to: "2026-09-23",
  timezone: "America/Chicago",
  families_lost: 4,
  by_reason: [
    { key: "moved_away", label: null, families: 1 },
    { key: "cost", label: null, families: 1 },
    { key: "other", label: null, families: 0 },
  ],
  with_reason: 2,
  by_transition: [
    { key: "cancelled_by_family", label: "Cancelled by the family", families: 1 },
    { key: "hold_expired", label: "Hold ran out", families: 1 },
  ],
  without_reason: 2,
};

test.describe("admin reports: attendance risk and families lost", () => {
  test("both cards render as tables and the range is sent", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));
    await page.route(ATTENDANCE_RISK_URL, (route) => fulfillJson(route, ATTENDANCE_RISK));
    const lostRanges: string[] = [];
    await page.route(FAMILIES_LOST_URL, (route) => {
      lostRanges.push(new URL(route.request().url()).search);
      return fulfillJson(route, FAMILIES_LOST);
    });

    await page.goto("/admin/reports");
    await openMonthCloseSection(page, "people");

    await expect(page.getByTestId("people-report-risk-class-table")).toBeVisible({
      timeout: 45_000,
    });
    const saturday = page.getByTestId("people-report-risk-class-row-sess-sat");
    await expect(saturday).toContainText("Saturday Squad");
    await expect(saturday).toContainText("Testcoach One");
    await expect(saturday).toContainText("67%");
    await expect(page.getByTestId("people-report-risk-class-row-sess-new")).toContainText(
      "No coach assigned",
    );
    await expect(page.getByTestId("people-report-risk-coach-row-coach-1")).toContainText(
      "Testcoach One",
    );
    await expect(page.getByTestId("people-report-attendance-risk-total")).toContainText(
      "2 students at risk of 4 students",
    );

    await expect(page.getByTestId("people-report-families-lost-table")).toBeVisible();
    await expect(page.getByTestId("people-report-families-lost-reason-moved_away")).toContainText(
      "Moved away",
    );
    await expect(page.getByTestId("people-report-families-lost-reason-other")).toHaveCount(0);
    await expect(
      page.getByTestId("people-report-families-lost-transition-cancelled_by_family"),
    ).toContainText("Cancelled by the family");
    await expect(page.getByTestId("people-report-families-lost-no-reason")).toContainText(
      "No reason recorded",
    );
    await expect(page.getByTestId("people-report-families-lost-total")).toContainText("4");
    expect(lostRanges[0]).toBe("");

    await page.getByTestId("people-report-families-lost-from").fill("2026-09-01");
    await expect.poll(() => lostRanges.some((q) => q.includes("from=2026-09-01"))).toBe(true);

    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("both cards show empty states on an empty academy", async ({ page }) => {
    await stubMonthCloseShell(page);
    await page.route(MONTH_CLOSE_URL, (route) => fulfillJson(route, monthClose()));
    await page.route(ATTENDANCE_RISK_URL, (route) =>
      fulfillJson(route, { ...ATTENDANCE_RISK, by_class: [], by_coach: [], students: 0, at_risk: 0 }),
    );
    await page.route(FAMILIES_LOST_URL, (route) =>
      fulfillJson(route, {
        ...FAMILIES_LOST,
        families_lost: 0,
        by_reason: FAMILIES_LOST.by_reason.map((row) => ({ ...row, families: 0 })),
        with_reason: 0,
        by_transition: [],
        without_reason: 0,
      }),
    );

    await page.goto("/admin/reports");
    await openMonthCloseSection(page, "people");
    await expect(page.getByTestId("people-report-attendance-risk-empty")).toBeVisible({
      timeout: 45_000,
    });
    await expect(page.getByTestId("people-report-families-lost-empty")).toBeVisible();
  });
});
