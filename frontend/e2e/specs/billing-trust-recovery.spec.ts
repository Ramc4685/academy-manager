import { test, expect } from "@playwright/test";

import {
  collectConsoleErrors,
  installTenantGuard,
} from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  PARENT_USER,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
  stubParentMessages,
  stubParentProfile,
} from "../fixtures/saas-stubs";

test.describe("billing trust and recovery surfaces", () => {
  test("parent payments are ledger-driven and expose invoice recovery actions", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    const retryRequests: Array<Record<string, unknown>> = [];

    await stubMe(page, PARENT_USER);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "parent" },
    ]);
    // The parent layout fetches this on every /parent/* page (issue #380).
    await stubParentProfile(page);
    await stubParentMessages(page);

    await page.route("**/api/v2/parent/payments", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        payments: [
          {
            payment_id: "lp_ledger_1",
            amount_cents: 4500,
            currency: "usd",
            status: "paid",
            refunded_cents: 0,
            created_at: "2026-06-01T12:00:00Z",
            session_id: null,
            stripe_invoice_id: "in_test_paid_1",
            stripe_payment_intent_id: "pi_test_paid_1",
          },
        ],
      });
    });
    await page.route("**/api/v2/parent/invoices", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        invoices: [
          {
            invoice_id: "inv-open",
            period: "2026-06",
            status: "open",
            total_cents: 9000,
            balance_due_cents: 4500,
            currency: "usd",
            due_date: "2026-06-15",
            pdf_url: null,
            created_at: "2026-06-01T00:00:00Z",
          },
        ],
      });
    });
    await page.route("**/api/v2/parent/invoices/inv-open", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        invoice_id: "inv-open",
        period: "2026-06",
        status: "open",
        total_cents: 9000,
        balance_due_cents: 4500,
        currency: "usd",
        due_date: "2026-06-15",
        pdf_url: null,
        created_at: "2026-06-01T00:00:00Z",
        lines: [
          {
            description: "Alice Chen monthly tuition",
            quantity: 1,
            unit_amount_cents: 9000,
            amount_cents: 9000,
          },
        ],
      });
    });
    await page.route("**/api/v2/parent/invoices/inv-open/pay", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      retryRequests.push(JSON.parse(route.request().postData() ?? "{}"));
      return fulfillJson(route, {
        invoice_id: "inv-open",
        redirect_url: "http://localhost:3001/parent/payments?invoice=paid",
      });
    });
    await page.route("**/api/v2/parent/enrollments", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: "enr-1",
            student_id: "stu-1",
            student_name: "Alice Chen",
            session_id: "sess-1",
            session_title: "Junior Badminton",
            status: "active",
            payment_mode: "monthly",
            subscription_status: "past_due",
            autopay_enrollment_status: "active",
            last_attempt_outcome: "declined",
          },
        ],
      });
    });
    await page.route("**/api/v2/parent/pause-requests", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { requests: [] });
    });
    await page.route("**/api/v2/parent/credits", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { balance_cents: 0, credits: [] });
    });
    await page.route("**/api/v2/parent/billing/portal", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, {
        redirect_url: "http://localhost:3001/stripe-portal-stub",
      });
    });

    await page.goto("/parent/payments");

    await expect(page.getByTestId("parent-payments")).toBeVisible();
    await expect(page.getByText("Balance due")).toBeVisible();
    await expect(page.getByText("open", { exact: true })).toBeVisible();
    await expect(page.getByText("$45.00").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Pay $45.00", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Billing portal" })).toBeVisible();
    await expect(page.getByText("Autopay active, payment issue")).toBeVisible();
    await expect(
      page.getByText("The latest autopay attempt failed."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Payment history" }).click();
    await expect(page.getByText("Invoice in_test_paid_1")).toBeVisible();

    await page.getByRole("button", { name: "View" }).click();
    await expect(page.getByText("Alice Chen monthly tuition × 1")).toBeVisible();

    await page.getByRole("button", { name: "Pay $45.00", exact: true }).click();
    await expect.poll(() => retryRequests.length).toBe(1);
    expect(retryRequests[0]).toMatchObject({
      success_url: expect.stringContaining("/parent/payments?invoice=paid"),
      cancel_url: expect.stringContaining("/parent/payments?invoice=cancelled"),
    });

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("admin payments expose failed-payment, webhook, Stripe, and reconciliation evidence", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, ADMIN_USER_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
    ]);
    await stubAcademy(page, ACADEMY_A);

    await page.route("**/api/v2/admin/payments*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        payments: [
          {
            payment_id: "pmt_failed_1",
            parent_id: "parent-1",
            parent_name: "Parent Example",
            student_id: "stu-1",
            student_name: "Alice Chen",
            enrollment_id: "enr-1",
            session_id: "sess-1",
            period: "2026-06",
            amount_cents: 9000,
            discount_cents: 0,
            final_amount_cents: 9000,
            amount_received_cents: 0,
            paid_amount_cents: 0,
            balance_due_cents: 9000,
            overpayment_credit_cents: 0,
            currency: "usd",
            status: "failed",
            refunded_cents: 0,
            invoice_number: "INV-2026-06-001",
            payment_method: "stripe",
            stripe_linked: true,
            stripe_customer_id: "cus_test_1",
            stripe_checkout_session_id: "cs_test_1",
            stripe_subscription_id: null,
            stripe_invoice_id: "in_test_failed_1",
            stripe_payment_intent_id: "pi_test_failed_1",
            reconciliation_status: "missing_allocation",
            created_at: "2026-06-02T12:00:00Z",
          },
        ],
      });
    });
    await page.route("**/api/v2/admin/billing/webhooks**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        events: [
          {
            event_id: "evt_failed_1",
            event_type: "invoice.payment_failed",
            status: "failed",
            object_id: "in_test_failed_1",
            object_type: "invoice",
            received_at: "2026-06-02T12:01:00Z",
            last_attempt_at: "2026-06-02T12:02:00Z",
            retry_count: 2,
            error_message: "card_declined",
          },
          {
            event_id: "evt_quarantine_1",
            event_type: "invoice.paid",
            status: "quarantined",
            object_id: "in_duplicate",
            object_type: "invoice",
            received_at: "2026-06-02T12:03:00Z",
            last_attempt_at: "2026-06-02T12:04:00Z",
            retry_count: 1,
            error_message: "duplicate obligation",
          },
        ],
      });
    });
    await page.route("**/api/v2/admin/billing/reconciliation**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        result: "MISSING_ALLOCATION",
        stripe_invoice_id: "in_test_failed_1",
        payment_intent_id: "pi_test_failed_1",
        stripe_customer_id: "cus_test_1",
        local_invoice_id: "inv-open",
        ledger_payment_id: "lp_ledger_1",
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
      });
    });

    await page.goto("/admin/payments");

    await expect(page.getByTestId("admin-payments")).toBeVisible();
    await expect(page.getByText("Failed payments")).toBeVisible();
    await expect(page.getByText("1").first()).toBeVisible();
    await expect(page.getByText("Failed webhook queue")).toBeVisible();
    await expect(page.getByText("invoice.payment_failed")).toBeVisible();
    await expect(page.getByText("QUARANTINED")).toBeVisible();
    await expect(page.getByText("duplicate obligation")).toBeVisible();
    await expect(page.getByTestId("payment-row-pmt_failed_1")).toContainText(
      "in_test_failed_1",
    );
    await expect(page.getByTestId("payment-row-pmt_failed_1")).toContainText(
      "pi_test_failed_1",
    );
    await expect(page.getByTestId("payment-row-pmt_failed_1")).toContainText(
      "missing allocation",
    );

    await page.getByPlaceholder("in_...").fill("in_test_failed_1");
    await page.getByPlaceholder("pi_...").fill("pi_test_failed_1");
    await page.getByRole("button", { name: "Run report" }).click();
    await expect(page.getByText("MISSING ALLOCATION", { exact: true })).toBeVisible();
    await expect(page.getByText("Ledger payment exists without payment allocation.")).toBeVisible();
    await expect(page.getByText("Ledger payment", { exact: true })).toBeVisible();
    await expect(page.getByText("Payment allocation", { exact: true })).toBeVisible();

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});
