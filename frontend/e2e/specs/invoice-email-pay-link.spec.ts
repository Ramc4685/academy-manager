import { test, expect, type Page } from "@playwright/test";

import { installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  PARENT_USER,
  fulfillJson,
  stubMe,
  stubMemberships,
  stubParentAcademy,
  stubParentMessages,
  stubParentProfile,
} from "../fixtures/saas-stubs";

// The invoice email's "Pay invoice" button links to /parent/payments?pay=<id>
// instead of a raw Stripe Checkout URL (which dies within 24h). Every visit
// must mint a fresh session through the parent pay endpoint.

async function stubPaymentsPage(page: Page, payStatus: number) {
  const payRequests: Array<Record<string, unknown>> = [];
  await stubMe(page, PARENT_USER);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "parent" },
  ]);
  await stubParentProfile(page);
  await stubParentMessages(page);
  await stubParentAcademy(page);
  for (const [path, body] of [
    ["**/api/v2/parent/payments", { payments: [] }],
    ["**/api/v2/parent/enrollments", { enrollments: [] }],
    ["**/api/v2/parent/pause-requests", { requests: [] }],
    ["**/api/v2/parent/credits", { balance_cents: 0, credits: [] }],
    [
      "**/api/v2/parent/invoices",
      {
        invoices: [
          {
            invoice_id: "inv-open",
            period: "2026-11",
            status: "open",
            total_cents: 9000,
            balance_due_cents: 9000,
            currency: "usd",
            due_date: "2026-11-15",
            pdf_url: null,
            created_at: "2026-11-01T00:00:00Z",
          },
        ],
      },
    ],
  ] as const) {
    await page.route(path, (route) =>
      route.request().method() === "GET" ? fulfillJson(route, body) : route.fallback(),
    );
  }
  await page.route("**/api/v2/parent/invoices/inv-open/pay", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    payRequests.push(JSON.parse(route.request().postData() ?? "{}"));
    if (payStatus !== 200) {
      return fulfillJson(route, { detail: "invoice is not payable" }, payStatus);
    }
    return fulfillJson(route, {
      invoice_id: "inv-open",
      redirect_url: `/stripe-checkout-stub?n=${payRequests.length}`,
    });
  });
  await page.route("**/api/v2/parent/invoices/pay-balance", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    payRequests.push({ balance: true, ...JSON.parse(route.request().postData() ?? "{}") });
    return fulfillJson(route, { redirect_url: "/stripe-checkout-stub?balance=1" });
  });
  await page.route("**/stripe-checkout-stub**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Stripe stub</h1>" }),
  );
  return payRequests;
}

test.describe("invoice email pay link", () => {
  test("each click on the emailed link mints a fresh checkout session", async ({ page }) => {
    const guard = installTenantGuard(page);
    const payRequests = await stubPaymentsPage(page, 200);

    await page.goto("/parent/payments?pay=inv-open");
    await expect(page).toHaveURL(/stripe-checkout-stub\?n=1/);

    // Same email, clicked again later: a second, independent mint.
    await page.goto("/parent/payments?pay=inv-open");
    await expect(page).toHaveURL(/stripe-checkout-stub\?n=2/);

    expect(payRequests).toHaveLength(2);
    expect(payRequests[0]).toMatchObject({
      enroll_autopay: false,
      success_url: expect.stringContaining("/parent/payments?invoice=paid"),
      cancel_url: expect.stringContaining("/parent/payments?invoice=cancelled"),
    });
    guard.assertNoLegacyApiCalls();
  });

  test("a bundled email's link starts the balance checkout", async ({ page }) => {
    const payRequests = await stubPaymentsPage(page, 200);

    await page.goto("/parent/payments?pay=balance");
    await expect(page).toHaveURL(/stripe-checkout-stub\?balance=1/);

    expect(payRequests).toHaveLength(1);
    expect(payRequests[0]).toMatchObject({ balance: true, enroll_autopay: false });
  });

  test("an unpayable invoice shows the error on the payments page", async ({ page }) => {
    const payRequests = await stubPaymentsPage(page, 409);

    await page.goto("/parent/payments?pay=inv-open");

    await expect(page.getByTestId("invoice-payment-error")).toBeVisible();
    await expect(page).not.toHaveURL(/pay=/);
    expect(payRequests).toHaveLength(1);
  });
});
