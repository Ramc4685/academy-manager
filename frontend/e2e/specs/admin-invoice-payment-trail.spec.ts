import { test, expect, type Page } from "@playwright/test";

import { ACADEMY_A, ADMIN_USER_A, fulfillJson, stubAcademy, stubMe, stubMemberships } from "../fixtures/saas-stubs";

/**
 * Usability study: an admin found paid records but could not trace one payment
 * to its invoice and on to the family's billing. The invoice dialog names the
 * payment and links to family billing; the deposit slip points back to invoices.
 */

const PAID = {
  payment_id: "inv-clean",
  invoice_id: "inv-clean",
  parent_id: "parent-2",
  parent_name: "Sam Samplefamily",
  student_id: "stu-2",
  student_name: "Casey Samplefamily",
  enrollment_id: null,
  session_id: null,
  period: "2026-10",
  amount_cents: 9000,
  discount_cents: 0,
  final_amount_cents: 9000,
  amount_received_cents: 9000,
  paid_amount_cents: 9000,
  balance_due_cents: 0,
  overpayment_credit_cents: 0,
  currency: "usd",
  status: "paid",
  refunded_cents: 0,
  invoice_number: "INV-2026-10-002",
  payment_method: "cash",
  stripe_linked: false,
  created_at: "2026-10-01T14:00:00Z",
  paid_at: "2026-10-02T15:00:00Z",
};

async function stubShell(page: Page): Promise<void> {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [{ academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" }]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/inbox/counts", (route) => fulfillJson(route, { counts: {}, total: 0 }));
}

test.use({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false });

test("a paid invoice names its payment and links to the family's billing", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v2/admin/payments*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { payments: [PAID], total: 1, limit: 200, offset: 0 });
  });
  await page.route("**/api/v2/admin/billing/invoices/inv-clean*", (route) =>
    fulfillJson(route, {
      invoice_id: "inv-clean",
      status: "paid",
      delivery_status: "not_sent",
      paid_amount_cents: 9000,
      due_amount_cents: 0,
      lines: [],
      allocations: [{ payment_id: "pay-clean-1", amount_cents: 9000 }],
      credit_usage: [],
    }),
  );
  await page.goto("/admin/payments?tab=invoices");
  await page.getByTestId("payment-row-inv-clean").getByRole("button", { name: "Invoice" }).click();
  await expect(page.getByText("Payment pay-clean-1")).toBeVisible();
  await expect(page.getByTestId("invoice-family-billing-link")).toHaveAttribute(
    "href",
    "/admin/families/parent-2?tab=billing",
  );
});

test("the deposit slip points to the invoice list for tracing one payment", async ({ page }) => {
  await stubShell(page);
  await page.route("**/api/v2/admin/reports/deposit-slip*", (route) =>
    fulfillJson(route, {
      period: "2026-10",
      days: [
        {
          date: "2026-10-02",
          count: 1,
          total_cents: 9000,
          methods: [{ method: "cash", count: 1, amount_cents: 9000 }],
        },
      ],
      total_cents: 9000,
      count: 1,
    }),
  );
  await page.goto("/admin/reports/deposit-slip");
  await expect(page.getByTestId("deposit-slip-invoices-link")).toHaveAttribute(
    "href",
    "/admin/payments?tab=invoices",
  );
});
