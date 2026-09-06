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
 * Payments — Collections tab (payments buckets spec §4, §7).
 *
 * The endpoint is stubbed with one family per bucket. Totals are what the
 * four tiles show; every family's `balance_cents` is what its row shows.
 */

const BUCKET_ORDER = [
  "failed_autopay",
  "past_due",
  "awaiting",
  "autopay_scheduled",
  "paused",
  "paid",
] as const;

const COLLECTIONS_FIXTURE = {
  period: "2026-09",
  generated_at: "2026-09-05T15:00:00Z",
  timezone: "America/Chicago",
  totals: {
    owed_cents: 111000,
    autopay_scheduled_cents: 138000,
    autopay_scheduled_count: 20,
    needs_action_count: 2,
    collected_cents: 201000,
  },
  buckets: [
    {
      key: "failed_autopay",
      count: 1,
      total_cents: 18000,
      families: [
        {
          parent_id: "parent-failed",
          parent_name: "Priya Raman",
          parent_email: "priya@example.com",
          action_invoice_id: "inv-failed",
          students: [{ student_id: "stu-failed", name: "Arjun", session_title: "Mon 5:00 Beginner" }],
          invoices: [
            {
              invoice_id: "inv-failed",
              invoice_number: "INV-2026-09-001",
              period: "2026-09",
              status: "open",
              total_cents: 18000,
              balance_due_cents: 18000,
              due_date: "2026-09-01",
              delivery_status: "sent",
            },
          ],
          balance_cents: 18000,
          leftover_balance_cents: 0,
          autopay: { status: "active", card_last4: "4242", charge_on: "2026-09-01", notice_sent_at: null },
          failure: {
            reason: "card_declined",
            attempt_count: 1,
            max_attempts: 4,
            next_retry_on: "2026-09-08",
            disabled: false,
          },
          pause: null,
          paid: null,
          last_reminder_at: null,
          actions: ["message", "record_payment"],
        },
      ],
    },
    {
      key: "past_due",
      count: 1,
      total_cents: 36000,
      families: [
        {
          parent_id: "parent-past-due",
          parent_name: "Dana Whitfield",
          parent_email: "dana@example.com",
          action_invoice_id: "inv-past-due",
          students: [
            { student_id: "stu-past-due", name: "Hannah", session_title: "Wed 6:15 Intermediate" },
          ],
          invoices: [
            {
              invoice_id: "inv-past-due",
              invoice_number: "INV-2026-09-002",
              period: "2026-09",
              status: "open",
              total_cents: 36000,
              balance_due_cents: 36000,
              due_date: "2026-09-01",
              delivery_status: "sent",
            },
          ],
          balance_cents: 36000,
          leftover_balance_cents: 0,
          autopay: null,
          failure: null,
          pause: null,
          paid: null,
          last_reminder_at: null,
          actions: ["send_reminder", "record_payment"],
        },
      ],
    },
    {
      key: "awaiting",
      count: 1,
      total_cents: 57000,
      families: [
        {
          parent_id: "parent-awaiting",
          parent_name: "Luis Ortega",
          parent_email: "luis@example.com",
          action_invoice_id: "inv-awaiting",
          students: [{ student_id: "stu-awaiting", name: "Mateo", session_title: "Sat 9:00 Advanced" }],
          invoices: [
            {
              invoice_id: "inv-awaiting",
              invoice_number: "INV-2026-09-003",
              period: "2026-09",
              status: "open",
              total_cents: 57000,
              balance_due_cents: 57000,
              due_date: "2026-09-15",
              delivery_status: "sent",
            },
          ],
          balance_cents: 57000,
          leftover_balance_cents: 0,
          autopay: null,
          failure: null,
          pause: null,
          paid: null,
          last_reminder_at: null,
          actions: ["send_reminder", "record_payment"],
        },
      ],
    },
    {
      key: "autopay_scheduled",
      count: 1,
      total_cents: 13800,
      families: [
        {
          parent_id: "parent-autopay",
          parent_name: "Mei Chen",
          parent_email: "mei@example.com",
          action_invoice_id: "inv-autopay",
          students: [{ student_id: "stu-autopay", name: "Kai", session_title: "Tue 5:00 Beginner" }],
          invoices: [
            {
              invoice_id: "inv-autopay",
              invoice_number: "INV-2026-09-004",
              period: "2026-09",
              status: "open",
              total_cents: 13800,
              balance_due_cents: 13800,
              due_date: "2026-09-15",
              delivery_status: "sent",
            },
          ],
          balance_cents: 13800,
          leftover_balance_cents: 0,
          autopay: {
            status: "active",
            card_last4: "1234",
            charge_on: "2026-09-15",
            notice_sent_at: "2026-09-08T14:00:00Z",
          },
          failure: null,
          pause: null,
          paid: null,
          last_reminder_at: null,
          actions: ["skip_month"],
        },
      ],
    },
    {
      key: "paused",
      count: 1,
      total_cents: 0,
      families: [
        {
          parent_id: "parent-paused",
          parent_name: "Sam Patel",
          parent_email: "sam@example.com",
          action_invoice_id: null,
          students: [{ student_id: "stu-paused", name: "Riya", session_title: "Thu 6:00 Intermediate" }],
          invoices: [],
          balance_cents: 0,
          leftover_balance_cents: 0,
          autopay: null,
          failure: null,
          pause: {
            enrollment_id: "enr-paused",
            resume_on: "2026-10-01",
            review_on: null,
            session_title: "Thu 6:00 Intermediate",
            student_name: "Riya",
          },
          paid: null,
          last_reminder_at: null,
          actions: ["resume"],
        },
      ],
    },
    {
      key: "paid",
      count: 1,
      total_cents: 201000,
      families: [
        {
          parent_id: "parent-paid",
          parent_name: "Grace Kim",
          parent_email: "grace@example.com",
          action_invoice_id: null,
          students: [{ student_id: "stu-paid", name: "Noah", session_title: "Fri 4:30 Beginner" }],
          invoices: [
            {
              invoice_id: "inv-paid",
              invoice_number: "INV-2026-09-005",
              period: "2026-09",
              status: "paid",
              total_cents: 201000,
              balance_due_cents: 0,
              due_date: "2026-09-01",
              delivery_status: "sent",
            },
          ],
          balance_cents: 0,
          leftover_balance_cents: 0,
          autopay: null,
          failure: null,
          pause: null,
          paid: { amount_cents: 201000, method: "card", paid_at: "2026-09-01T14:05:00Z" },
          last_reminder_at: null,
          actions: [],
        },
      ],
    },
  ],
};

async function stubAdminShell(page: Page): Promise<void> {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  // Generic payments stub first: Playwright matches routes last-in-first-out,
  // so the collections stub below wins for its own URL while every other
  // /admin/payments* URL (the All invoices table) keeps this empty list.
  await page.route("**/api/v2/admin/payments*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { payments: [] });
  });
  await page.route("**/api/v2/admin/billing/webhooks*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { events: [] });
  });
}

async function stubCollections(page: Page): Promise<void> {
  await page.route("**/api/v2/admin/payments/collections*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, COLLECTIONS_FIXTURE);
  });
}

test.describe("admin payments buckets", () => {
  test("renders six buckets in spec order with counts and tile totals", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await stubCollections(page);

    await page.goto("/admin/payments");

    await expect(page.getByTestId("admin-payments")).toBeVisible();
    await expect(page.getByTestId("collections-tile-owed-value")).toHaveText("$1,110.00");
    await expect(page.getByTestId("collections-tile-autopay-value")).toHaveText("$1,380.00");
    await expect(page.getByTestId("collections-tile-needs-action-value")).toHaveText("2");
    await expect(page.getByTestId("collections-tile-collected-value")).toHaveText("$2,010.00");

    const renderedOrder = await page
      .locator('section[data-testid^="bucket-"]')
      .evaluateAll((sections) =>
        sections.map((el) => el.getAttribute("data-testid")?.replace(/^bucket-/, "")),
      );
    expect(renderedOrder).toEqual([...BUCKET_ORDER]);

    for (const key of BUCKET_ORDER) {
      await expect(page.getByTestId(`bucket-${key}-count`)).toHaveText("1");
    }
    await expect(page.getByTestId("family-row-parent-past-due")).toContainText("Dana Whitfield");
    await expect(page.getByTestId("family-row-parent-past-due")).toContainText("$360.00");
    await expect(page.getByTestId("family-row-parent-failed")).toContainText("$180.00");
    await expect(page.getByTestId("family-row-parent-awaiting")).toContainText("$570.00");

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("paid bucket is collapsed by default and expands on click", async ({ page }) => {
    await stubAdminShell(page);
    await stubCollections(page);

    await page.goto("/admin/payments");

    const details = page.getByTestId("bucket-paid").locator("details");
    await expect(page.getByTestId("bucket-paid-toggle")).toBeVisible();
    await expect(details).toHaveJSProperty("open", false);
    await expect(page.getByTestId("family-row-parent-paid")).toBeHidden();

    await page.getByTestId("bucket-paid-toggle").click();

    await expect(details).toHaveJSProperty("open", true);
    await expect(page.getByTestId("family-row-parent-paid")).toBeVisible();
    await expect(page.getByTestId("family-row-parent-paid")).toContainText("$2,010.00");
  });

  test("record payment on a past-due row opens the dialog prefilled with the balance", async ({
    page,
  }) => {
    await stubAdminShell(page);
    await stubCollections(page);

    await page.goto("/admin/payments");

    await page.getByTestId("action-record_payment-parent-past-due").click();

    await expect(page.getByTestId("record-payment-dialog")).toBeVisible();
    await expect(page.getByTestId("record-payment-invoice")).toHaveValue("inv-past-due");
    await expect(page.getByTestId("record-payment-amount")).toHaveValue("360.00");
  });

  test("send reminder posts the row's parent id and the row reports it", async ({ page }) => {
    const reminderBodies: Array<Record<string, unknown>> = [];
    await stubAdminShell(page);
    await stubCollections(page);
    await page.route("**/api/v2/admin/dues-reminders", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>;
      reminderBodies.push(body);
      return fulfillJson(route, {
        sent: 1,
        blocked: false,
        reason: null,
        selected_parent_ids: body.parent_ids ?? [],
        generated_invoice_artifacts: 0,
      });
    });

    await page.goto("/admin/payments");

    await page.getByTestId("action-send_reminder-parent-past-due").click();

    await expect.poll(() => reminderBodies.length).toBe(1);
    expect(reminderBodies[0]).toMatchObject({ parent_ids: ["parent-past-due"] });
    await expect(page.getByTestId("row-status-parent-past-due")).toHaveText("Reminder sent");
  });

  test("an empty response renders zero tiles and every empty-bucket line", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    // The collections URL answers `{ payments: [] }` — the shape every
    // existing payments spec returns — and the page must still render.
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/payments/collections*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { payments: [] });
    });

    await page.goto("/admin/payments");

    await expect(page.getByTestId("collections-tile-owed-value")).toHaveText("$0.00");
    await expect(page.getByTestId("collections-tile-autopay-value")).toHaveText("$0.00");
    await expect(page.getByTestId("collections-tile-needs-action-value")).toHaveText("0");
    await expect(page.getByTestId("collections-tile-collected-value")).toHaveText("$0.00");
    for (const key of BUCKET_ORDER) {
      await expect(page.getByTestId(`bucket-${key}-count`)).toHaveText("0");
    }
    for (const key of BUCKET_ORDER.filter((k) => k !== "paid")) {
      await expect(page.getByTestId(`bucket-${key}-empty`)).toBeVisible();
    }
    // Paid is collapsed; its empty line is in the DOM behind the toggle.
    await expect(page.getByTestId("bucket-paid-empty")).toBeAttached();
    await page.getByTestId("bucket-paid-toggle").click();
    await expect(page.getByTestId("bucket-paid-empty")).toBeVisible();

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("?tab=invoices shows the All invoices table area", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await stubCollections(page);

    await page.goto("/admin/payments?tab=invoices");

    await expect(page.getByTestId("admin-payments")).toBeVisible();
    await expect(page.getByTestId("payments-tab-invoices")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("payments-all-invoices")).toBeVisible();
    await expect(page.getByTestId("payments-empty")).toBeVisible();
    await expect(page.getByTestId("payments-collections")).toHaveCount(0);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
