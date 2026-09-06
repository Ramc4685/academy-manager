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

/** Family billing page (spec 2026-09-05-family-billing §6, §8) with a stubbed family. */

const FAMILY = {
  generated_at: "2026-09-10T15:00:00Z",
  timezone: "America/Chicago",
  today: "2026-09-10",
  parent: { parent_id: "parent-1", name: "Sahaya Vinodh", email: "sahaya@example.com", phone: null },
  header: {
    balance_cents: 7000,
    open_invoice_count: 1,
    available_credit_cents: 0,
    last_payment: {
      amount_cents: 6000,
      method: "card",
      paid_at: "2026-08-04T14:00:00Z",
      invoice_ids: ["inv-aug"],
    },
    autopay: {
      state: "on",
      active_count: 1,
      total_count: 1,
      card_last4: "4242",
      card_label: "Visa",
      next_charge_on: "2026-09-08",
      next_charge_invoice_id: "inv-sep",
      last_failure: null,
    },
    registration: { state: "registered", card_on_file: true, last_invited_at: null },
    enrollment_counts: { active: 1, paused: 1, cancelled: 0 },
  },
  students: [
    {
      student_id: "stu-hannah",
      name: "Hannah",
      status: "active",
      enrollments: [
        {
          enrollment_id: "enr-hannah",
          session_id: "sess-wed",
          session_title: "Wed 6:15 Intermediate",
          schedule: "Wed 18:15",
          status: "paused",
          monthly_price_cents: 7000,
          override_price_cents: null,
          autopay_status: "paused",
          recurring_discount: null,
          resume_on: "2026-10-01",
          actions: ["recurring_discount"],
        },
      ],
    },
    {
      student_id: "stu-arjun",
      name: "Arjun",
      status: "active",
      enrollments: [
        {
          enrollment_id: "enr-arjun",
          session_id: "sess-sat",
          session_title: "Sat 9:00 Beginners",
          schedule: "Sat 09:00",
          status: "active",
          monthly_price_cents: 6000,
          override_price_cents: null,
          autopay_status: "active",
          recurring_discount: null,
          resume_on: null,
          actions: ["recurring_discount"],
        },
      ],
    },
  ],
  invoices: [
    {
      invoice_id: "inv-sep",
      invoice_number: "INV-2026-09-003",
      period: "2026-09",
      student_id: "stu-arjun",
      student_name: "Arjun",
      enrollment_id: "enr-arjun",
      status: "open",
      total_cents: 7000,
      paid_cents: 0,
      balance_due_cents: 7000,
      due_date: "2026-09-08",
      created_at: "2026-09-01T06:00:00Z",
      paid_at: null,
      voided_at: null,
      void_reason: null,
      settlement_unlinked: false,
      delivery: { status: "sent", last_sent_at: "2026-09-01T06:05:00Z", kind: "autopay_notice" },
      allocations: [],
      credits: [],
      chargeable: true,
      actions: ["send", "record_payment", "charge_card", "void", "discount_once"],
    },
    {
      invoice_id: "inv-aug",
      invoice_number: "INV-2026-08-001",
      period: "2026-08",
      student_id: "stu-arjun",
      student_name: "Arjun",
      enrollment_id: "enr-arjun",
      status: "paid",
      total_cents: 6000,
      paid_cents: 6000,
      balance_due_cents: 0,
      due_date: "2026-08-08",
      created_at: "2026-08-01T06:00:00Z",
      paid_at: "2026-08-04T14:00:00Z",
      voided_at: null,
      void_reason: null,
      settlement_unlinked: false,
      delivery: { status: "sent", last_sent_at: "2026-08-01T06:05:00Z", kind: "autopay_notice" },
      allocations: [
        {
          payment_id: "pay-aug",
          amount_cents: 6000,
          method: "card",
          paid_at: "2026-08-04T14:00:00Z",
          stripe_payment_intent_id: "pi_aug",
        },
      ],
      credits: [],
      chargeable: false,
      actions: ["refund"],
    },
  ],
  timeline: [
    {
      at: "2026-09-04T20:00:00Z",
      kind: "money",
      code: "invoice_voided",
      summary: "Sep 2026 invoice voided · Hannah · enrollment paused",
      invoice_id: "inv-h",
      invoice_ids: ["inv-h"],
      enrollment_id: null,
      student_name: "Hannah",
      actor_id: null,
      reason: "enrollment paused",
      amount_cents: null,
      muted: false,
    },
    {
      at: "2026-09-01T06:05:00Z",
      kind: "comms",
      code: "autopay_notice_emailed",
      summary: "Autopay notice emailed · Sep 2026 · Arjun",
      invoice_id: "inv-sep",
      invoice_ids: ["inv-sep"],
      enrollment_id: null,
      student_name: "Arjun",
      actor_id: null,
      reason: null,
      amount_cents: null,
      muted: true,
    },
    {
      at: "2026-08-04T14:00:00Z",
      kind: "money",
      code: "payment_received",
      summary: "$60 received · card ••4242",
      invoice_id: null,
      invoice_ids: ["inv-aug"],
      enrollment_id: null,
      student_name: null,
      actor_id: null,
      reason: "pay-aug",
      amount_cents: 6000,
      muted: false,
    },
  ],
  actions: ["autopay_off", "send_invoice", "record_payment"],
  warnings: [],
};

async function stubShell(page: Page, owner: boolean): Promise<void> {
  await stubMe(page, owner ? ADMIN_USER_A : { ...ADMIN_USER_A, roles: ["admin"] });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: owner ? "owner" : "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
}

async function setup(page: Page, opts: { owner: boolean; view?: unknown }) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubShell(page, opts.owner);
  const posts: { url: string; body: unknown }[] = [];
  await page.route("**/api/v2/admin/families/**", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      posts.push({ url: req.url(), body: req.postDataJSON() });
      return fulfillJson(route, { paused_count: 1, active_count_before: 1, warnings: [] });
    }
    return fulfillJson(route, opts.view ?? FAMILY);
  });
  await page.route("**/api/v2/admin/billing/invoices/**", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      posts.push({ url: req.url(), body: req.postDataJSON() });
      return fulfillJson(route, { ok: true });
    }
    return fulfillJson(route, {
      entries: [{ action: "manual_payment_recorded", actor_id: "admin-1" }],
    });
  });
  await page.goto("/admin/families/parent-1");
  await expect(page.getByTestId("admin-family-billing")).toBeVisible();
  return { errors, posts };
}

test.describe("Family billing", () => {
  test("header, students, invoices and timeline render from one response", async ({ page }) => {
    const { errors } = await setup(page, { owner: true });
    await expect(page.getByTestId("family-balance")).toContainText("$70");
    await expect(page.getByTestId("family-autopay-hint")).toContainText(
      "Visa ••4242 · next charge Sep 8",
    );
    await expect(page.getByTestId("family-last-payment")).toContainText("$60");
    await expect(page.getByTestId("family-registration-chip")).toContainText("Card on file");
    await expect(page.getByTestId("enrollment-row-enr-hannah")).toContainText("resumes Oct 1");
    await expect(page.getByTestId("invoice-row-inv-sep")).toContainText("Sep 2026 · Arjun");
    await page.getByTestId("invoice-expand-inv-aug").click();
    await expect(page.getByTestId("invoice-allocations-inv-aug")).toContainText("pi_aug");
    await expect(page.getByTestId("timeline-entry-autopay_notice_emailed")).toHaveAttribute(
      "data-tone",
      "muted",
    );
    await expect(page.getByTestId("timeline-entry-payment_received")).toContainText(
      "$60 received",
    );
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("turning autopay off asks for a reason and posts to the pause route", async ({ page }) => {
    const { posts } = await setup(page, { owner: true });
    await page.getByTestId("family-autopay-toggle").click();
    await expect(page.getByTestId("reason-dialog")).toBeVisible();
    await expect(page.getByRole("button", { name: "Turn off" })).toBeDisabled();
    await page.getByTestId("reason-input").fill("parent asked to pause");
    await page.getByRole("button", { name: "Turn off" }).click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0].url).toContain("/admin/families/parent-1/autopay/pause");
    expect(posts[0].body).toMatchObject({ reason: "parent asked to pause" });
    expect((posts[0].body as { request_id: string }).request_id).toBeTruthy();
  });

  test("needs_consent disables the toggle and offers the invite", async ({ page }) => {
    const view = {
      ...FAMILY,
      actions: ["send_invite"],
      header: {
        ...FAMILY.header,
        autopay: {
          ...FAMILY.header.autopay,
          state: "needs_consent",
          card_last4: null,
          card_label: null,
          next_charge_on: null,
        },
        registration: { state: "not_invited", card_on_file: false, last_invited_at: null },
      },
    };
    await setup(page, { owner: true, view });
    await expect(page.getByTestId("family-autopay-toggle")).toBeDisabled();
    await expect(page.getByTestId("family-autopay-hint")).toContainText("Needs parent consent");
    await expect(page.getByTestId("family-send-invite")).toBeVisible();
  });

  test("void requires a reason and posts it; refund hidden for a plain admin", async ({ page }) => {
    const { posts } = await setup(page, { owner: true });
    await page.getByTestId("invoice-action-void-inv-sep").click();
    await expect(page.getByRole("button", { name: "Void invoice" }).last()).toBeDisabled();
    await page.getByTestId("reason-input").fill("duplicate invoice");
    await page.getByRole("button", { name: "Void invoice" }).last().click();
    await expect.poll(() => posts.length).toBe(1);
    expect(posts[0].url).toContain("/admin/billing/invoices/inv-sep/void");
    expect(posts[0].body).toEqual({ reason: "duplicate invoice" });
  });

  test("admin without owner scope sees no owner-only buttons", async ({ page }) => {
    const view = {
      ...FAMILY,
      invoices: FAMILY.invoices.map((i) => ({
        ...i,
        actions: i.actions.filter((a) => !["void", "refund", "discount_once"].includes(a)),
      })),
    };
    await setup(page, { owner: false, view });
    await expect(page.getByTestId("invoice-action-void-inv-sep")).toHaveCount(0);
    await expect(page.getByTestId("invoice-action-refund-inv-aug")).toHaveCount(0);
    await expect(page.getByTestId("family-fix")).not.toContainText("Refund");
    await expect(page.getByTestId("family-fix")).toContainText("Charge card now");
  });

  test("full audit calls the audit route", async ({ page }) => {
    await setup(page, { owner: true });
    await page.getByTestId("invoice-expand-inv-aug").click();
    await page.getByTestId("invoice-audit-inv-aug").click();
    await expect(page.getByTestId("invoice-audit-drawer")).toContainText("manual_payment_recorded");
  });

  test("billing-setup redirects to families and the list links to a family", async ({ page }) => {
    installTenantGuard(page);
    await stubShell(page, true);
    await page.route("**/api/v2/admin/billing/setup*", (route) =>
      fulfillJson(route, {
        rows: [
          {
            parent_id: "parent-1",
            parent_name: "Sahaya Vinodh",
            parent_email: "sahaya@example.com",
            students: [{ student_id: "stu-arjun", full_name: "Arjun" }],
            registration_state: "card_on_file",
            card_label: "Visa",
            card_last4: "4242",
            autopay_active_count: 1,
            autopay_eligible_count: 0,
            outstanding_balance_cents: 7000,
            charge_invoice_id: null,
            charge_amount_cents: 0,
            charge_autopay_eligible: false,
            last_invited_at: null,
          },
        ],
        summary: {
          families_total: 1,
          families_registered: 1,
          families_no_card: 0,
          outstanding_total_cents: 7000,
        },
        next_cursor: null,
      }),
    );
    await page.goto("/admin/billing-setup");
    // Mobile redirects are slow under load in this suite (the same 5s
    // toHaveURL flake the /admin/parents and /admin/coaches redirect tests
    // hit); give the navigation the longer budget used elsewhere.
    await expect(page).toHaveURL(/\/admin\/families$/, { timeout: 30_000 });
    await expect(page.getByTestId("admin-families")).toBeVisible();
    await expect(page.getByTestId("family-link-parent-1")).toHaveAttribute(
      "href",
      "/admin/families/parent-1",
    );
  });
});
