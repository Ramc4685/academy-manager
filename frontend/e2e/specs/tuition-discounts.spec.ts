import { expect, test, type Page, type Route } from "@playwright/test";

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

type StudentDetail = Record<string, unknown> & {
  enrolled_sessions: Array<Record<string, unknown> & { enrollment_id: string }>;
};

const adminInvoiceDetail = {
  invoice_id: "inv-discounts",
  invoice_number: "INV-2026-06-DISC",
  period: "2026-06",
  status: "open",
  currency: "usd",
  subtotal_cents: 22_000,
  discount_cents: 12_400,
  total_cents: 9_600,
  balance_due_cents: 9_600,
  due_amount_cents: 9_600,
  paid_amount_cents: 0,
  delivery_status: "not_sent",
  sent_at: null,
  last_sent_at: null,
  lines: [
    {
      line_id: "line-scholarship-tuition",
      description: "Scholarship student monthly tuition",
      amount_cents: 10_000,
      line_type: "tuition",
      quantity: 1,
      unit_amount_cents: 10_000,
      source_type: "enrollment",
      source_id: "enr-scholarship",
    },
    {
      line_id: "line-scholarship-discount",
      description: "Scholarship discount",
      amount_cents: -10_000,
      line_type: "discount",
      quantity: 1,
      unit_amount_cents: -10_000,
      source_type: "tuition_discount",
      source_id: "disc-scholarship",
    },
    {
      line_id: "line-coach-child-tuition",
      description: "Coach child monthly tuition",
      amount_cents: 12_000,
      line_type: "tuition",
      quantity: 1,
      unit_amount_cents: 12_000,
      source_type: "enrollment",
      source_id: "enr-coach-child",
    },
    {
      line_id: "line-coach-child-discount",
      description: "Coach child discount",
      amount_cents: -2_400,
      line_type: "discount",
      quantity: 1,
      unit_amount_cents: -2_400,
      source_type: "tuition_discount",
      source_id: "disc-coach-child",
    },
  ],
  allocations: [],
  credit_usage: [],
  invoice_pdf_artifact_id: null,
  receipt_artifact_id: null,
};

const REPORTS_DASHBOARD_EMPTY = {
  period: "2026-06",
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

/**
 * Month close carries the tuition discount card now (spec §5). The figures are
 * the same two discounts the admin set above, summed for the month.
 */
const MONTH_CLOSE_WITH_DISCOUNTS = {
  generated_at: "2026-06-30T14:00:00Z",
  timezone: "America/Chicago",
  period: "2026-06",
  invoices: {
    generated: 1,
    emailed: 0,
    autopay_notices: 0,
    not_sent: 1,
    voided: 0,
    voided_cents: 0,
    void_reasons: [],
  },
  money: {
    billed_cents: 9_600,
    collected_cents: 0,
    outstanding_cents: 9_600,
    collection_rate: 0,
  },
  autopay_run: {
    charge_on: null,
    charge_on_varies: false,
    has_run: false,
    scheduled: { count: 0, cents: 0 },
    succeeded: { count: 0, cents: 0 },
    failed: { count: 0, cents: 0 },
    pending: { count: 0, cents: 0 },
  },
  odd: [],
  tuition_discounts: {
    gross_cents: 22_000,
    discount_cents: 12_400,
    net_cents: 9_600,
    by_category: [
      { category: "scholarship", amount_cents: 10_000 },
      { category: "coach_child", amount_cents: 2_400 },
    ],
  },
  warnings: [],
};

function baseStudentFixture(): StudentDetail {
  return {
    student_id: "student-discounts",
    full_name: "Maya Discount",
    parent_id: "parent-discounts",
    parent_name: "Rina Discount",
    parent_email: "rina@example.com",
    parent_phone: "555-0102",
    status: "active",
    active_session_count: 2,
    last_seen_at: "2026-06-12T15:00:00Z",
    attendance_rate: 0.94,
    dues_status: "due",
    date_of_birth: "2014-02-10",
    level: "intermediate",
    notes: null,
    parent_details: null,
    previous_experience: null,
    medical_notes: null,
    emergency_contact_name: null,
    emergency_contact_phone: null,
    t_shirt_size: null,
    waiver_status: "signed",
    waiver_signed_at: "2026-05-10T15:00:00Z",
    waiver_version: "2026-v1",
    recent_attendance: [],
    enrolled_sessions: [
      {
        enrollment_id: "enr-scholarship",
        session_id: "sess-scholarship",
        session_title: "Scholarship Singles",
        location: "Court 1",
        start_at: "2026-06-02T21:00:00Z",
        end_at: "2026-06-02T22:00:00Z",
        status: "active",
        payment_mode: "monthly",
        subscription_status: "active",
        amount_cents: 10_000,
        discount: null,
      },
      {
        enrollment_id: "enr-coach-child",
        session_id: "sess-coach-child",
        session_title: "Coach Kids Doubles",
        location: "Court 2",
        start_at: "2026-06-03T21:00:00Z",
        end_at: "2026-06-03T22:00:00Z",
        status: "active",
        payment_mode: "monthly",
        subscription_status: "active",
        amount_cents: 12_000,
        discount: null,
      },
    ],
    payment_history: [
      {
        payment_id: "inv-discounts",
        session_id: null,
        period: "2026-06",
        amount_cents: 9_600,
        paid_amount_cents: 0,
        balance_due_cents: 9_600,
        status: "open",
        payment_method: "manual",
        invoice_number: "INV-2026-06-DISC",
        created_at: "2026-06-01T15:00:00Z",
      },
    ],
    current_payment: {
      amount_cents: 9_600,
      source: "invoice",
      status: "open",
      period: "2026-06",
      payment_id: "inv-discounts",
      session_id: null,
    },
    outstanding_balance_cents: 9_600,
  };
}

function applyDiscount(
  student: StudentDetail,
  enrollmentId: string,
  discount: Record<string, unknown>,
) {
  student.enrolled_sessions = student.enrolled_sessions.map((session) =>
    session.enrollment_id === enrollmentId ? { ...session, discount } : session,
  );
}

async function stubAdminStudentDiscounts(page: Page, student: StudentDetail) {
  await page.route("**/api/v2/admin/users?role=parent", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      users: [
        {
          user_id: "parent-discounts",
          email: "rina@example.com",
          display_name: "Rina Discount",
          role: "parent",
          status: "active",
          phone: "555-0102",
        },
      ],
    });
  });
  await page.route("**/api/v2/admin/programs*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { programs: [] });
  });
  // The student page's Billing tab reads these two. Unstubbed they 500, and
  // this spec asserts an empty console, so the failure surfaces as two opaque
  // "Failed to load resource" lines rather than a missing mock.
  // `admin-students.spec.ts` already stubs the same pair for the same reason.
  await page.route("**/api/v2/admin/billing-enrollments*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { enrollments: [] });
  });
  await page.route("**/api/v2/admin/session-types*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { session_types: [] });
  });
  await page.route("**/api/v2/admin/students/student-discounts", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, student);
  });
  await page.route("**/api/v2/admin/billing/invoices/inv-discounts", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, adminInvoiceDetail);
  });
}

async function stubParentInvoiceDiscounts(page: Page) {
  await page.route("**/api/v2/parent/payments", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { payments: [] });
  });
  await page.route("**/api/v2/parent/invoices", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      invoices: [
        {
          invoice_id: "inv-discounts",
          period: "2026-06",
          status: "open",
          total_cents: 9_600,
          balance_due_cents: 9_600,
          currency: "usd",
          due_date: "2026-06-15",
          pdf_url: null,
          created_at: "2026-06-01T00:00:00Z",
        },
      ],
    });
  });
  await page.route("**/api/v2/parent/invoices/inv-discounts", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      invoice_id: "inv-discounts",
      period: "2026-06",
      status: "open",
      total_cents: 9_600,
      balance_due_cents: 9_600,
      currency: "usd",
      due_date: "2026-06-15",
      pdf_url: null,
      created_at: "2026-06-01T00:00:00Z",
      lines: [
        {
          description: "Scholarship student monthly tuition",
          quantity: 1,
          unit_amount_cents: 10_000,
          amount_cents: 10_000,
        },
        {
          description: "Scholarship discount",
          label: "Scholarship discount",
          quantity: 1,
          unit_amount_cents: -10_000,
          amount_cents: -10_000,
        },
        {
          description: "Coach child monthly tuition",
          quantity: 1,
          unit_amount_cents: 12_000,
          amount_cents: 12_000,
        },
        {
          description: "Coach child discount",
          label: "Coach child discount",
          quantity: 1,
          unit_amount_cents: -2_400,
          amount_cents: -2_400,
        },
      ],
    });
  });
  await page.route("**/api/v2/parent/enrollments", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { enrollments: [] });
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
}

test.describe("tuition discounts", () => {
  test("admin sets scholarship waiver and coach-child partial discounts", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);
    const student = baseStudentFixture();
    const discountRequests: Array<{ enrollmentId: string; body: Record<string, unknown> }> = [];

    await stubMe(page, ADMIN_USER_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
    ]);
    await stubAcademy(page, ACADEMY_A);
    await stubAdminStudentDiscounts(page, student);
    await page.route("**/api/v2/admin/enrollments/*/tuition-discount", (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const url = new URL(route.request().url());
      const enrollmentId = url.pathname.split("/").at(-2) ?? "";
      const body = route.request().postDataJSON() as Record<string, unknown>;
      discountRequests.push({ enrollmentId, body });
      if (enrollmentId === "enr-scholarship") {
        applyDiscount(student, enrollmentId, {
          category: "scholarship",
          category_label: null,
          kind: "waiver",
          label: "Scholarship",
          gross_cents: 10_000,
          discount_cents: 10_000,
          net_cents: 0,
          status: "active",
          effective_start: body.effective_start,
          effective_end: null,
        });
      }
      if (enrollmentId === "enr-coach-child") {
        applyDiscount(student, enrollmentId, {
          category: "coach_child",
          category_label: null,
          kind: "percent",
          label: "Coach child",
          gross_cents: 12_000,
          discount_cents: 2_400,
          net_cents: 9_600,
          status: "active",
          effective_start: body.effective_start,
          effective_end: null,
        });
      }
      return fulfillJson(route, { ok: true });
    });

    await page.goto("/admin/students/student-discounts");
    await page.getByRole("tab", { name: "Sessions" }).click();
    const sessions = page.getByTestId("admin-student-enrolled-sessions");
    const scholarshipRow = sessions
      .locator("tbody tr")
      .filter({ hasText: "Scholarship Singles" });
    const coachChildRow = sessions
      .locator("tbody tr")
      .filter({ hasText: "Coach Kids Doubles" });

    await scholarshipRow.getByRole("button", { name: "Discount" }).click();
    await expect(page.getByRole("dialog", { name: "Tuition discount" })).toBeVisible();
    await page.getByRole("button", { name: "Save discount" }).click();
    await expect(page.getByRole("dialog", { name: "Tuition discount" })).toHaveCount(0);
    await expect(scholarshipRow).toContainText("Scholarship");
    await expect(scholarshipRow).toContainText("$0");

    await coachChildRow.getByRole("button", { name: "Discount", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Tuition discount" });
    await dialog.locator("select").nth(0).selectOption("coach_child");
    await dialog.locator("select").nth(1).selectOption("percent");
    await dialog.locator("input[type='number']").fill("20");
    await page.getByRole("button", { name: "Save discount" }).click();
    await expect(dialog).toHaveCount(0);

    expect(discountRequests).toMatchObject([
      {
        enrollmentId: "enr-scholarship",
        body: { category: "scholarship", kind: "waiver" },
      },
      {
        enrollmentId: "enr-coach-child",
        body: { category: "coach_child", kind: "percent", percent_bps: 2000 },
      },
    ]);
    await expect(coachChildRow).toContainText("Coach child");
    await expect(coachChildRow).toContainText("$96");

    // The invoice ledger moved to the family billing page (spec
    // 2026-09-05-family-billing §6); the student Billing tab now links to it.
    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page.getByTestId("admin-student-family-billing-link")).toBeVisible();

    await page.route("**/api/v2/admin/families/parent-discounts/billing", (route) =>
      fulfillJson(route, familyBillingWithDiscountedInvoice()),
    );
    await page.goto("/admin/families/parent-discounts");
    await expect(page.getByTestId("family-invoices")).toBeVisible();
    await expect(page.getByTestId("invoice-row-inv-discounts")).toContainText("$96");
    await page.getByTestId("invoice-expand-inv-discounts").click();
    const lines = page.getByTestId("invoice-lines-inv-discounts");
    await expect(lines).toContainText("Scholarship discount");
    await expect(lines).toContainText("Coach child discount");
    await expect(lines).toContainText("-$100");
    await expect(lines).toContainText("-$24");

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("the tuition discount summary now lives on Month close", async ({ page }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, ADMIN_USER_A);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
    ]);
    await stubAcademy(page, ACADEMY_A);
    // Catch-all first (Playwright matches LIFO), so the page's other feeds
    // answer `{}` and only the assertions below depend on real shapes.
    await page.route("**/api/v2/admin/**", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {});
    });
    // The page's other feeds need their real shapes: the catch-all `{}` would
    // put `dashboard.payroll` at undefined and send the page to the error
    // boundary before the discount card ever renders.
    await page.route("**/api/v2/admin/reports/dashboard*", (route) =>
      fulfillJson(route, REPORTS_DASHBOARD_EMPTY),
    );
    await page.route("**/api/v2/admin/reports/projected-income*", (route) =>
      fulfillJson(route, {
        period: "2026-07",
        total_cents: 0,
        autopay_cents: 0,
        manual_cents: 0,
        autopay_enrollment_count: 0,
        manual_enrollment_count: 0,
        by_session: [],
        empty: true,
      }),
    );
    await page.route("**/api/v2/admin/finance/revenue*", (route) =>
      fulfillJson(route, { by_month: {} }),
    );
    // Named in full: a `*` glob stops at `/`, so `admin/reports*` would miss it.
    await page.route("**/api/v2/admin/reports/month-close*", (route) =>
      fulfillJson(route, MONTH_CLOSE_WITH_DISCOUNTS),
    );

    await page.goto("/admin/reports");
    const card = page.getByTestId("tuition-discounts-section");
    await expect(card).toBeVisible({ timeout: 45_000 });
    await expect(card).toContainText("$220.00");
    await expect(card).toContainText("$124.00");
    await expect(card).toContainText("$96.00");
    await expect(page.getByTestId("tuition-discounts-row-scholarship")).toContainText("$100.00");
    await expect(page.getByTestId("tuition-discounts-row-coach_child")).toContainText("$24.00");

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("parent invoice shows public discount lines without private notes", async ({
    page,
  }) => {
    const guard = installTenantGuard(page);
    const errors = collectConsoleErrors(page);

    await stubMe(page, PARENT_USER);
    await stubMemberships(page, [
      { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "parent" },
    ]);
    // The parent layout fetches this on every /parent/* page (issue #380).
    await stubParentProfile(page);
    await stubParentMessages(page);
    await stubParentInvoiceDiscounts(page);

    await page.goto("/parent/payments");
    await expect(page.getByTestId("parent-payments")).toBeVisible();
    await page.getByRole("button", { name: "View" }).click();
    await expect(page.getByText("Scholarship discount")).toBeVisible();
    await expect(page.getByText("Coach child discount")).toBeVisible();
    await expect(page.getByText("-$100.00")).toBeVisible();
    await expect(page.getByText("-$24.00")).toBeVisible();
    await expect(page.getByText("Internal scholarship note")).toHaveCount(0);

    guard.assertNoLegacyApiCalls();
    expect(errors, `Console errors: ${errors.join("\n")}`).toEqual([]);
  });
});

/**
 * Minimal family-billing response carrying the discounted invoice, so the
 * ledger assertions live where the invoice now renders. The line items come
 * from the existing `/admin/billing/invoices/inv-discounts` stub, which the
 * expanded row fetches.
 */
function familyBillingWithDiscountedInvoice() {
  return {
    generated_at: "2026-06-10T12:00:00Z",
    timezone: "America/Chicago",
    today: "2026-06-10",
    parent: {
      parent_id: "parent-discounts",
      name: "Discount Parent",
      email: "discount@example.com",
      phone: null,
    },
    header: {
      balance_cents: 9600,
      open_invoice_count: 1,
      available_credit_cents: 0,
      last_payment: null,
      autopay: {
        state: "needs_consent",
        active_count: 0,
        total_count: 1,
        card_last4: null,
        card_label: null,
        next_charge_on: null,
        next_charge_invoice_id: null,
        last_failure: null,
      },
      registration: { state: "not_invited", card_on_file: false, last_invited_at: null },
      enrollment_counts: { active: 1, paused: 0, cancelled: 0 },
    },
    students: [],
    invoices: [
      {
        invoice_id: "inv-discounts",
        invoice_number: "INV-DISC-1",
        period: "2026-06",
        student_id: "student-discounts",
        student_name: "Discount Student",
        enrollment_id: "enr-discounts",
        status: "open",
        total_cents: 9600,
        paid_cents: 0,
        balance_due_cents: 9600,
        due_date: "2026-06-08",
        created_at: "2026-06-01T06:00:00Z",
        paid_at: null,
        voided_at: null,
        void_reason: null,
        settlement_unlinked: false,
        delivery: { status: "sent", last_sent_at: "2026-06-01T06:05:00Z", kind: "invoice" },
        allocations: [],
        credits: [],
        chargeable: false,
        actions: [],
      },
    ],
    timeline: [],
    actions: ["send_invite"],
    warnings: [],
  };
}
