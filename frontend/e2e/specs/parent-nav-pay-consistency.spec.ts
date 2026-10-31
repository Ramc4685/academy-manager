/**
 * Issue #843 — parent shell consistency.
 *
 * Three things the parent app got wrong on a phone:
 *   1. Requests and Profile were not in the shell chrome, so "request a
 *      makeup" was only reachable from a card low on Home.
 *   2. Pay actions wore four different colours; one primary pay style now.
 *   3. "Billing portal" and "View detail" were well under the 44px target.
 *
 * Mocks the v2 BFF at the Playwright route layer, like parent-home.spec.ts —
 * `fixtures/mock-api.ts` carries no parent stubs, so every parent endpoint
 * these pages touch is stubbed here.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

async function json(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/** GET-only stub; anything else falls through to the fixture's handlers. */
async function stubGet(page: Page, pattern: string, body: unknown): Promise<void> {
  await page.route(pattern, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return json(route, body);
  });
}

/** Everything the parent shell reads on every /parent/* page. */
async function stubParentShell(page: Page): Promise<void> {
  await page.route("**/api/v2/me", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return json(route, {
      user_id: "user-parent-e2e",
      email: "parent@example.com",
      academy_id: "academy-e2e",
      roles: ["parent"],
    });
  });
  await stubGet(page, "**/api/v2/parent/messages", { messages: [] });
  await stubGet(page, "**/api/v2/parent/profile", {
    user_id: "user-parent-e2e",
    display_name: "Pat Kim",
    email: "parent@example.com",
    email_confirmed: true,
    phone: "555-0100",
    children: [],
    gaps: { parent: [], children: {}, is_complete: true },
  });
}

/** The kid-first Home, with nothing to distract from the shell chrome. */
async function stubHome(page: Page): Promise<void> {
  await stubGet(page, "**/api/v2/parent/academy", {
    display_name: "Aces Academy",
    timezone: "America/Chicago",
    contact_email: "hello@aces.example",
    contact_phone: null,
    hours_text: null,
    address: "1 Court Lane",
    logo_url: null,
  });
  await stubGet(page, "**/api/v2/parent/home", {
    children: [],
    balance: {
      amount_due_cents: 0,
      currency: "usd",
      due_date: null,
      open_invoice_count: 0,
      payment_failed: false,
    },
    month_label: "September",
    timezone: "America/Chicago",
  });
  await stubGet(page, "**/api/v2/parent/enrollments", { enrollments: [] });
  await stubGet(page, "**/api/v2/parent/attendance", { records: [] });
  await stubGet(page, "**/api/v2/parent/progress", { notes: [] });
  await stubGet(page, "**/api/v2/parent/payments", { payments: [] });
  await stubGet(page, "**/api/v2/parent/invoices", { invoices: [] });
  await stubGet(page, "**/api/v2/parent/credits", { balance_cents: 0, credits: [] });
  await stubGet(page, "**/api/v2/parent/waivers/current", {
    required: false,
    waiver_template_id: null,
    title: null,
    version: null,
    body: null,
    students: [],
  });
}

const OPEN_INVOICE = {
  invoice_id: "inv-open-1",
  period: "2026-09",
  status: "open",
  total_cents: 12000,
  balance_due_cents: 12000,
  currency: "usd",
  due_date: "2026-09-12",
  pdf_url: null,
  created_at: "2026-09-01T00:00:00Z",
  void_reason: null,
};

const PAID_INVOICE = {
  invoice_id: "inv-paid-1",
  period: "2026-08",
  status: "paid",
  total_cents: 9000,
  balance_due_cents: 0,
  currency: "usd",
  due_date: "2026-08-12",
  pdf_url: null,
  created_at: "2026-08-01T00:00:00Z",
  void_reason: null,
};

/** The Payments page: one payable invoice, one settled one, one enrollment. */
async function stubPayments(page: Page): Promise<void> {
  await stubGet(page, "**/api/v2/parent/payments", { payments: [] });
  await stubGet(page, "**/api/v2/parent/invoices", {
    invoices: [OPEN_INVOICE, PAID_INVOICE],
  });
  await stubGet(page, "**/api/v2/parent/credits", { balance_cents: 0, credits: [] });
  await stubGet(page, "**/api/v2/parent/pause-requests", { requests: [] });
  await stubGet(page, "**/api/v2/parent/enrollments", {
    enrollments: [
      {
        enrollment_id: "enr-1",
        student_id: "st-1",
        student_name: "Ava Kim",
        session_id: "sess-1",
        session_title: "Junior Beginners",
        status: "active",
        payment_mode: "monthly",
        subscription_status: null,
        autopay_enrollment_status: null,
      },
    ],
  });
}

async function backgroundColor(page: Page, testId: string): Promise<string> {
  return page
    .getByTestId(testId)
    .evaluate((el) => window.getComputedStyle(el).backgroundColor);
}

test.describe("parent shell — nav, pay style, touch targets (#843)", () => {
  test("the shell exposes Requests in the bottom nav and Profile in the header", async ({
    page,
  }) => {
    await stubParentShell(page);
    await stubHome(page);

    await page.goto("/parent/dashboard");
    await expect(page.getByTestId("parent-dashboard")).toBeVisible();

    const requestsTab = page.getByTestId("nav-requests");
    await expect(requestsTab).toHaveAttribute("href", "/parent/requests");
    await expect(requestsTab).toContainText("Requests");

    // Profile lives in the header, not only behind the dismissible
    // profile-gap banner (which this stub suppresses: gaps.is_complete).
    const profileLink = page.getByTestId("nav-profile");
    await expect(profileLink).toHaveAttribute("href", "/parent/profile");
    await expect
      .poll(async () => (await profileLink.boundingBox())?.height ?? 0)
      .toBeGreaterThanOrEqual(44);
  });

  test("every pay action on Payments wears the same primary style", async ({ page }) => {
    await stubParentShell(page);
    await stubPayments(page);

    await page.goto("/parent/payments");
    await expect(page.getByTestId("parent-payments")).toBeVisible();

    const balancePay = await backgroundColor(page, "pay-balance");
    const invoicePay = await backgroundColor(page, "pay-invoice-inv-open-1");
    const autopay = await backgroundColor(page, "start-autopay-enr-1");

    expect(balancePay).toBe(invoicePay);
    expect(autopay).toBe(invoicePay);
    // …and it is the DS primary cobalt, not a gradient or a volt fill.
    expect(balancePay).toBe("rgb(37, 99, 235)");
  });

  test("Billing portal and View detail meet the 44px touch target", async ({ page }) => {
    await stubParentShell(page);
    await stubPayments(page);

    await page.goto("/parent/payments");
    await expect(page.getByTestId("parent-payments")).toBeVisible();

    for (const testId of ["billing-portal", "invoice-detail-toggle-inv-paid-1"]) {
      const target = page.getByTestId(testId);
      await expect(target).toBeVisible();
      await expect
        .poll(async () => (await target.boundingBox())?.height ?? 0, {
          message: `${testId} height`,
        })
        .toBeGreaterThanOrEqual(44);
      await expect
        .poll(async () => (await target.boundingBox())?.width ?? 0, {
          message: `${testId} width`,
        })
        .toBeGreaterThanOrEqual(44);
    }
  });

  test("Payments sends pause-enrollment to Children instead of owning the form", async ({
    page,
  }) => {
    await stubParentShell(page);
    await stubPayments(page);

    await page.goto("/parent/payments");
    await expect(page.getByTestId("parent-payments")).toBeVisible();

    const manage = page.getByTestId("manage-enrollment-enr-1");
    await expect(manage).toHaveAttribute("href", "/parent/children");
    // The pause form no longer lives on the money page.
    await expect(page.getByTestId("pause-enrollment-form")).toHaveCount(0);
  });
});
