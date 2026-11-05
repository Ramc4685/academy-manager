import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  academyMonth,
  academyToday,
  api,
  apiRaw,
  billAndSend,
  createDailyClass,
  enroll,
  idToken,
  seededCoachId,
  seededFamily,
  signedInPage,
  usd,
  type SeededFamily,
} from "../fixtures/real-backend";
import { REAL_AUTH_USERS } from "../fixtures/real-auth-users";

/**
 * Real-backend journeys: real Next.js frontend, real FastAPI backend, real
 * MongoDB, Firebase Auth emulator. No `page.route` anywhere — this is the one
 * suite that proves enrollment, invoicing, payment and attendance agree
 * across the admin, coach and parent personas.
 *
 * Independence: every test creates its own class (unique title and price) and
 * uses its own seeded single-child family (a distinct `slot`), so tests can run
 * in any order and a retry only adds rows the assertions never look at.
 *
 * Seeding uses the same /api/v2 admin routes the UI calls, never raw Mongo.
 *
 * Payment: CI has no Stripe test keys, so the parent cannot reach Stripe
 * Checkout. The payment is the admin's real "record payment" route (cash),
 * which settles the invoice through the same ledger a webhook does.
 *
 * Opt-in behind REAL_AUTH_E2E=1, like real-auth-smoke.spec.ts.
 */
const REAL_AUTH_ENABLED = process.env.REAL_AUTH_E2E === "1";

type Ctx = { adminToken: string; coachId: string; family: SeededFamily };

async function setup(request: APIRequestContext, slot: number): Promise<Ctx> {
  const adminToken = await idToken(request, REAL_AUTH_USERS.admin);
  const coachId = await seededCoachId(request, adminToken, "Gowtham");
  const family = await seededFamily(request, adminToken, slot);
  return { adminToken, coachId, family };
}

type ParentInvoice = {
  invoice_id: string;
  period: string;
  status: string;
  total_cents: number;
  balance_due_cents: number;
  enrollment_id: string | null;
};

async function parentInvoices(request: APIRequestContext, parentToken: string) {
  const body: { invoices: ParentInvoice[] } = await api(request, parentToken, "GET", "/parent/invoices");
  return body.invoices;
}

async function liveEnrollmentIds(request: APIRequestContext, parentToken: string) {
  const body: { enrollments: { enrollment_id: string; status: string; departed: boolean }[] } =
    await api(request, parentToken, "GET", "/parent/enrollments");
  return body.enrollments.filter((e) => !e.departed && e.status === "active").map((e) => e.enrollment_id);
}

test.describe("real-backend journeys", () => {
  test.skip(
    !REAL_AUTH_ENABLED,
    "Set REAL_AUTH_E2E=1 and run with playwright.ci-real-auth.config.ts against a seeded local stack.",
  );
  test.slow();

  test("admin adds a student on the class roster and the parent sees the class", async ({
    browser,
    request,
    baseURL,
  }) => {
    const { adminToken, coachId, family } = await setup(request, 0);
    const klass = await createDailyClass(request, adminToken, coachId, "roster", 4101);

    const admin = await signedInPage(browser, baseURL!, REAL_AUTH_USERS.admin, /\/admin/);
    await admin.goto(`/admin/sessions/${klass.sessionId}`, { waitUntil: "domcontentloaded" });
    await expect(admin.getByTestId("admin-session-detail")).toBeVisible({ timeout: 60_000 });
    // The shell re-navigates once its auth check settles; open dialogs after that.
    await admin.waitForLoadState("networkidle");
    await admin.getByRole("button", { name: "Add to roster" }).first().click();
    const dialog = admin.getByRole("dialog");
    await dialog.locator("select").first().selectOption(family.studentId);
    const created = admin.waitForResponse(
      (r) => r.url().includes("/api/v2/admin/enrollments") && r.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "Enroll" }).click();
    expect((await created).status()).toBe(200);
    await expect(admin.getByText(family.studentName).first()).toBeVisible({ timeout: 30_000 });

    const parent = await signedInPage(browser, baseURL!, family.parent, /\/parent/);
    await parent.goto("/parent/children", { waitUntil: "domcontentloaded" });
    await expect(parent.getByTestId("parent-children")).toBeVisible({ timeout: 60_000 });
    await expect(parent.getByText(klass.title).first()).toBeVisible({ timeout: 30_000 });
  });

  test("a monthly invoice for the enrollment shows the parent the right amount due", async ({
    browser,
    request,
    baseURL,
  }) => {
    const { adminToken, coachId, family } = await setup(request, 1);
    const amount = 4202;
    const klass = await createDailyClass(request, adminToken, coachId, "invoice", amount);
    const enrollmentId = await enroll(request, adminToken, klass.sessionId, family);
    const invoice = await billAndSend(request, adminToken, enrollmentId, academyMonth(0));
    expect(invoice.total_cents).toBe(amount);

    const parentToken = await idToken(request, family.parent);
    const seen = (await parentInvoices(request, parentToken)).find(
      (i) => i.invoice_id === invoice.invoice_id,
    );
    expect(seen).toMatchObject({ status: "open", total_cents: amount, balance_due_cents: amount });

    const parent = await signedInPage(browser, baseURL!, family.parent, /\/parent/);
    await parent.goto("/parent/payments", { waitUntil: "domcontentloaded" });
    await expect(parent.getByTestId("parent-payments")).toBeVisible({ timeout: 60_000 });
    await expect(parent.getByTestId("parent-payments").getByText(usd(amount)).first()).toBeVisible({
      timeout: 30_000,
    });
    // Open and payable: the parent gets a Pay button for exactly this invoice.
    await expect(parent.getByTestId(`pay-invoice-${invoice.invoice_id}`)).toBeVisible();
  });

  test("a recorded payment marks the invoice paid for both the parent and the admin", async ({
    browser,
    request,
    baseURL,
  }) => {
    const { adminToken, coachId, family } = await setup(request, 2);
    const amount = 4303;
    const klass = await createDailyClass(request, adminToken, coachId, "payment", amount);
    const enrollmentId = await enroll(request, adminToken, klass.sessionId, family);
    const invoice = await billAndSend(request, adminToken, enrollmentId, academyMonth(0));

    const paid: { invoice_status: string; balance_due_cents: number } = await api(
      request,
      adminToken,
      "POST",
      `/admin/billing/invoices/${invoice.invoice_id}/record-payment`,
      { amount_cents: amount, payment_method: "cash", notes: "real-backend e2e" },
    );
    expect(paid).toMatchObject({ invoice_status: "paid", balance_due_cents: 0 });

    const parentToken = await idToken(request, family.parent);
    const seen = (await parentInvoices(request, parentToken)).find(
      (i) => i.invoice_id === invoice.invoice_id,
    );
    expect(seen).toMatchObject({ status: "paid", balance_due_cents: 0 });

    const parent = await signedInPage(browser, baseURL!, family.parent, /\/parent/);
    await parent.goto("/parent/payments", { waitUntil: "domcontentloaded" });
    const payments = parent.getByTestId("parent-payments");
    await expect(payments).toBeVisible({ timeout: 60_000 });
    await expect(payments.getByText(usd(amount)).first()).toBeVisible({ timeout: 30_000 });
    // Settled: the invoice is still listed, but no longer offers a Pay button.
    await expect(parent.getByTestId(`invoice-detail-toggle-${invoice.invoice_id}`)).toBeVisible();
    await expect(parent.getByTestId(`pay-invoice-${invoice.invoice_id}`)).toHaveCount(0);

    const admin = await signedInPage(browser, baseURL!, REAL_AUTH_USERS.admin, /\/admin/);
    await admin.goto(`/admin/families/${family.parentId}?tab=billing`, {
      waitUntil: "domcontentloaded",
    });
    const row = admin.getByTestId(`invoice-row-${invoice.invoice_id}`);
    await expect(row).toBeVisible({ timeout: 60_000 });
    await expect(row).toContainText(/paid/i);
    await expect(row).toContainText(usd(amount));
  });

  test("a coach marks a student present and the admin and parent both see it", async ({
    browser,
    request,
    baseURL,
  }) => {
    const { adminToken, coachId, family } = await setup(request, 3);
    const klass = await createDailyClass(request, adminToken, coachId, "attendance", 4404);
    await enroll(request, adminToken, klass.sessionId, family);

    const coachToken = await idToken(request, REAL_AUTH_USERS.coach);
    const today: { sessions: { session_id: string; occurrence_id: string }[] } = await api(
      request,
      coachToken,
      "GET",
      "/coach/today",
    );
    const occurrence = today.sessions.find((s) => s.session_id === klass.sessionId);
    expect(occurrence, `today's occurrence of ${klass.title}`).toBeTruthy();
    const occurrenceId = occurrence!.occurrence_id;
    expect(occurrenceId).toContain(academyToday());

    const coach = await signedInPage(browser, baseURL!, REAL_AUTH_USERS.coach, /\/coach/);
    await coach.goto(`/coach/sessions/${encodeURIComponent(occurrenceId)}`, {
      waitUntil: "domcontentloaded",
    });
    const present = coach.getByTestId(`mark-${family.studentId}-present`);
    await expect(present).toBeVisible({ timeout: 60_000 });
    const marked = coach.waitForResponse(
      (r) => r.url().includes("/api/v2/coach/") && r.url().includes("attendance") && r.request().method() !== "GET",
    );
    await present.click();
    expect((await marked).ok()).toBe(true);
    await expect(present).toHaveAttribute("aria-pressed", "true");

    // Admin side: the occurrence's attendance record the admin roster reads.
    await expect
      .poll(
        async () => {
          const body: { attendance: { student_id: string; status: string }[] } = await api(
            request,
            adminToken,
            "GET",
            `/admin/session-occurrences/${encodeURIComponent(occurrenceId)}/attendance`,
          );
          return body.attendance.find((a) => a.student_id === family.studentId)?.status;
        },
        { timeout: 30_000 },
      )
      .toBe("present");

    const parent = await signedInPage(browser, baseURL!, family.parent, /\/parent/);
    await parent.goto("/parent/attendance", { waitUntil: "domcontentloaded" });
    const attendance = parent.getByTestId("parent-attendance");
    await expect(attendance).toBeVisible({ timeout: 60_000 });
    // The record for this class (not some other seeded class) carries the mark.
    const record = attendance.locator("div.p-4").filter({ hasText: klass.title });
    await expect(record.first()).toBeVisible({ timeout: 30_000 });
    await expect(record.first()).toContainText(/present/i);
  });

  test("a parent cannot see another family's class or invoice", async ({
    browser,
    request,
    baseURL,
  }) => {
    const adminToken = await idToken(request, REAL_AUTH_USERS.admin);
    const coachId = await seededCoachId(request, adminToken, "Gowtham");
    const mine = await seededFamily(request, adminToken, 4);
    const theirs = await seededFamily(request, adminToken, 5);
    const amount = 4505;
    const klass = await createDailyClass(request, adminToken, coachId, "isolation", amount);
    const theirEnrollment = await enroll(request, adminToken, klass.sessionId, theirs);
    const theirInvoice = await billAndSend(request, adminToken, theirEnrollment, academyMonth(0));

    const myToken = await idToken(request, mine.parent);
    // Direct reads of the other family's records are refused (404, existence
    // not leaked), not filtered to empty.
    const direct = await apiRaw(request, myToken, "GET", `/parent/invoices/${theirInvoice.invoice_id}`);
    expect(direct.status()).toBe(404);
    expect(await direct.text()).not.toContain(theirs.studentName);
    expect((await parentInvoices(request, myToken)).map((i) => i.invoice_id)).not.toContain(
      theirInvoice.invoice_id,
    );
    // Wrong persona gets exactly 404, never 401/403 (docs/security-matrix.md).
    const adminRoute = await apiRaw(request, myToken, "GET", `/admin/families/${theirs.parentId}/billing`);
    expect(adminRoute.status()).toBe(404);

    const parent = await signedInPage(browser, baseURL!, mine.parent, /\/parent/);
    await parent.goto("/parent/children", { waitUntil: "domcontentloaded" });
    await expect(parent.getByTestId("parent-children")).toBeVisible({ timeout: 60_000 });
    await expect(parent.getByText(mine.studentName).first()).toBeVisible({ timeout: 30_000 });
    await expect(parent.getByText(theirs.studentName)).toHaveCount(0);
    await expect(parent.getByText(klass.title)).toHaveCount(0);
    await parent.goto("/parent/payments", { waitUntil: "domcontentloaded" });
    await expect(parent.getByTestId("parent-payments")).toBeVisible({ timeout: 60_000 });
    await expect(parent.getByText(usd(amount))).toHaveCount(0);
  });

  test("withdrawing a student stops billing for later months", async ({
    browser,
    request,
    baseURL,
  }) => {
    const { adminToken, coachId, family } = await setup(request, 6);
    const amount = 4606;
    const klass = await createDailyClass(request, adminToken, coachId, "withdraw", amount);
    const enrollmentId = await enroll(request, adminToken, klass.sessionId, family);
    const thisMonth = await billAndSend(request, adminToken, enrollmentId, academyMonth(0));
    // Next month was already drafted before the family left.
    const nextMonth: { invoice_id: string } = await api(
      request,
      adminToken,
      "POST",
      `/admin/enrollments/${enrollmentId}/invoices/bill-period`,
      { period: academyMonth(1) },
    );

    const parentToken = await idToken(request, family.parent);
    expect(await liveEnrollmentIds(request, parentToken)).toContain(enrollmentId);

    await api(request, adminToken, "POST", `/admin/enrollments/${enrollmentId}/withdraw`, {
      effective_date: academyToday(),
      reason: "real-backend e2e withdraw",
      outcome: "credit",
    });

    // The later month's invoice is voided, this month's stays, and no later
    // month can be billed for the dropped enrollment.
    const invoices = await parentInvoices(request, parentToken);
    expect(invoices.find((i) => i.invoice_id === nextMonth.invoice_id)?.status).toBe("void");
    expect(invoices.find((i) => i.invoice_id === thisMonth.invoice_id)?.status).not.toBe("void");
    const later = await apiRaw(
      request,
      adminToken,
      "POST",
      `/admin/enrollments/${enrollmentId}/invoices/bill-period`,
      { period: academyMonth(2) },
    );
    expect(later.status()).toBe(409);
    expect(
      invoices.filter(
        (i) => i.enrollment_id === enrollmentId && i.period > academyMonth(0) && i.status !== "void",
      ),
    ).toEqual([]);

    const parent = await signedInPage(browser, baseURL!, family.parent, /\/parent/);
    await parent.goto("/parent/children", { waitUntil: "domcontentloaded" });
    await expect(parent.getByTestId("parent-children")).toBeVisible({ timeout: 60_000 });
    await expect(parent.getByText(family.studentName).first()).toBeVisible({ timeout: 30_000 });
    // The parent's own view no longer has it as a live enrollment (it was
    // before the drop). The parent views keep only one past class per child,
    // so the departed row itself is not asserted: on a retry an earlier
    // attempt's drop can be the one carried.
    expect(await liveEnrollmentIds(request, parentToken)).not.toContain(enrollmentId);
    await expect(
      parent.getByRole("listitem").filter({ hasText: klass.title }).filter({ hasText: "Active enrollment" }),
    ).toHaveCount(0);
  });
});
