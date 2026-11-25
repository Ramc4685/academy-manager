import { test, expect, type Page } from "@playwright/test";

import { ACADEMY_A, ADMIN_USER_A, fulfillJson, stubAcademy, stubMe, stubMemberships } from "../fixtures/saas-stubs";

/**
 * A disputed payment says so on the All invoices list (#980). The dispute is
 * answered in the academy's Stripe dashboard; the row only has to show it.
 */

const SHOTS_DIR = process.env.DISPUTE_SHOTS_DIR;

const PAYMENTS = [
  {
    payment_id: "inv-disputed",
    invoice_id: "inv-disputed",
    parent_id: "parent-1",
    parent_name: "Jordan Testfamily",
    student_id: "stu-1",
    student_name: "Riley Testfamily",
    enrollment_id: null,
    session_id: null,
    period: "2026-10",
    amount_cents: 13000,
    discount_cents: 0,
    final_amount_cents: 13000,
    amount_received_cents: 13000,
    paid_amount_cents: 13000,
    balance_due_cents: 0,
    overpayment_credit_cents: 0,
    currency: "usd",
    status: "paid",
    refunded_cents: 0,
    invoice_number: "INV-2026-10-001",
    payment_method: "stripe_autopay",
    stripe_linked: true,
    stripe_payment_intent_id: "pi_fake_disputed",
    dispute_id: "dp_fake_1",
    dispute_status: "needs_response",
    dispute_reason: "fraudulent",
    dispute_amount_cents: 13000,
    dispute_outcome: null,
    disputed_at: "2026-10-12T15:00:00Z",
    created_at: "2026-10-01T15:00:00Z",
    paid_at: "2026-10-03T15:00:00Z",
  },
  {
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
    payment_method: "stripe_autopay",
    stripe_linked: true,
    created_at: "2026-10-01T14:00:00Z",
    paid_at: "2026-10-02T15:00:00Z",
  },
];

async function stubShell(page: Page): Promise<void> {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [{ academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" }]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/payments*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { payments: PAYMENTS, total: PAYMENTS.length, limit: 200, offset: 0 });
  });
  await page.route("**/api/v2/admin/inbox/counts", (route) => fulfillJson(route, { counts: {}, total: 0 }));
}

async function expectDisputeNote(page: Page, shot: string): Promise<void> {
  await stubShell(page);
  await page.goto("/admin/payments?tab=invoices");
  await expect(page.getByText("Riley Testfamily").first()).toBeVisible();
  if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/${shot}.png`, fullPage: true });
  await expect(page.getByTestId("payment-dispute-note-inv-disputed")).toHaveText(
    "Disputed $130.00 · fraudulent · needs response",
  );
  await expect(page.getByTestId("payment-dispute-note-inv-clean")).toHaveCount(0);
}

test("phone row shows the open dispute on a disputed payment", async ({ page }) => {
  await expectDisputeNote(page, "phone");
});

test.describe("desktop table", () => {
  test.use({ viewport: { width: 1280, height: 800 }, isMobile: false, hasTouch: false });

  test("shows the open dispute in the status column", async ({ page }) => {
    await expectDisputeNote(page, "desktop");
  });
});
