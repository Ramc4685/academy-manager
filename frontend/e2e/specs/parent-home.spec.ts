/**
 * Parent home — kid-first cards, balance banner, Progress deep link (slice 4).
 *
 * Mocks the v2 BFF at the Playwright route layer, like
 * parent-self-service.spec.ts. `fixtures/mock-api.ts` carries no parent
 * stubs, so every parent endpoint this page touches is stubbed here —
 * including the ones behind the sections that stay (recent activity, primary
 * action, academy contact), which would otherwise hang.
 *
 * Runs on chromium-mobile / webkit-mobile: the parent shell is mobile-first
 * (capped at max-w-md) and `chromium-desktop` deliberately matches only the
 * three admin specs.
 */

import { test, expect } from "../fixtures/mock-api";
import type { Page, Route } from "@playwright/test";

const TZ = "America/Chicago";

interface HomeChild {
  student_id: string;
  full_name: string;
  next_session: Record<string, unknown> | null;
  attendance_this_month: { present: number; total: number };
  latest_milestone: { kind: "note" | "skill"; label: string; at: string } | null;
}

interface HomeBalance {
  amount_due_cents: number;
  currency: string;
  due_date: string | null;
  open_invoice_count: number;
  payment_failed: boolean;
}

const ZERO_BALANCE: HomeBalance = {
  amount_due_cents: 0,
  currency: "usd",
  due_date: null,
  open_invoice_count: 0,
  payment_failed: false,
};

function nextSession(overrides: Record<string, unknown> = {}) {
  return {
    occurrence_id: "occ-1",
    session_id: "sess-1",
    session_title: "Junior Beginners",
    location: "Court 2",
    // 23:00 UTC is 6:00 PM the SAME day in Chicago.
    start_at: "2026-09-10T23:00:00Z",
    end_at: "2026-09-11T00:00:00Z",
    coach_name: null,
    ...overrides,
  };
}

const AVA: HomeChild = {
  student_id: "st-1",
  full_name: "Ava Kim",
  next_session: nextSession(),
  attendance_this_month: { present: 6, total: 7 },
  latest_milestone: { kind: "skill", label: "Backhand lift", at: "2025-08-20T14:00:00Z" },
};

const BO: HomeChild = {
  student_id: "st-2",
  full_name: "Bo Chen",
  next_session: null,
  attendance_this_month: { present: 0, total: 0 },
  latest_milestone: null,
};

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
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

async function stubParentIdentity(page: Page): Promise<void> {
  await page.route("**/api/v2/me", async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return json(route, {
      user_id: "user-parent-e2e",
      email: "parent@example.com",
      academy_id: "academy-e2e",
      roles: ["parent"],
    });
  });
}

/** Everything the parent shell and the retained Home sections read. */
async function stubParentShell(page: Page): Promise<void> {
  await stubParentIdentity(page);
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
  await stubGet(page, "**/api/v2/parent/academy", {
    display_name: "Aces Academy",
    timezone: TZ,
    contact_email: "hello@aces.example",
    contact_phone: null,
    hours_text: null,
    address: "1 Court Lane",
    logo_url: null,
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

async function stubHome(
  page: Page,
  children: HomeChild[],
  balance: HomeBalance = ZERO_BALANCE,
): Promise<void> {
  await stubGet(page, "**/api/v2/parent/home", {
    children,
    balance,
    month_label: "September",
    timezone: TZ,
  });
}

test.describe("parent home — kid-first cards", () => {
  test.beforeEach(async ({ page }) => {
    await stubParentShell(page);
  });

  test("two children render one card each, and no billing content", async ({ page }) => {
    await stubHome(page, [AVA, BO]);

    await page.goto("/parent/dashboard");
    await expect(page.getByTestId("parent-dashboard")).toBeVisible();

    const cards = page.getByTestId("parent-child-cards").getByRole("listitem");
    await expect(cards).toHaveCount(2);

    // Stubbed order is the card order — parents learn positions.
    const first = page.getByTestId("parent-child-card-st-1");
    await expect(first).toContainText("Ava Kim");
    await expect(first).toContainText("Thu, Sep 10 · 6:00 PM CDT");
    await expect(first).toContainText("Court 2");
    await expect(first).toContainText("6 of 7 sessions this month");
    await expect(first).toContainText("Backhand lift");
    await expect(first).toContainText("Aug 20");

    // A child with nothing yet still gets a complete, honest card.
    const second = page.getByTestId("parent-child-card-st-2");
    await expect(second).toContainText("Bo Chen");
    await expect(second).toContainText("No upcoming sessions");
    await expect(second).toContainText("No sessions marked yet this month");
    await expect(second).toContainText("No milestones yet");

    await expect(page.getByTestId("parent-balance-banner")).toHaveCount(0);
  });

  test("a balance due shows the banner with an amount, a due date and one Pay action", async ({
    page,
  }) => {
    await stubHome(page, [AVA], {
      amount_due_cents: 12000,
      currency: "usd",
      due_date: "2026-09-12",
      open_invoice_count: 1,
      payment_failed: false,
    });

    await page.goto("/parent/dashboard");

    const banner = page.getByTestId("parent-balance-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute("role", "status");
    await expect(banner).toContainText("$120.00 due");
    await expect(banner).toContainText("Due Sep 12");

    const pay = page.getByTestId("parent-balance-pay");
    await expect(pay).toHaveAttribute("href", "/parent/payments");
    // Poll rather than measure once: the card animates in and react-query can
    // re-render underneath a single boundingBox() call, which then reads null.
    await expect
      .poll(async () => (await pay.boundingBox())?.height ?? 0)
      .toBeGreaterThanOrEqual(44);
    await expect
      .poll(async () => (await pay.boundingBox())?.width ?? 0)
      .toBeGreaterThanOrEqual(44);
  });

  test("a failed payment shows the banner even when nothing is due", async ({ page }) => {
    await stubHome(page, [AVA], {
      ...ZERO_BALANCE,
      payment_failed: true,
    });

    await page.goto("/parent/dashboard");

    const banner = page.getByTestId("parent-balance-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Payment didn't go through");
    await expect(banner).toContainText("Update your payment method to stay enrolled.");
    await expect(page.getByTestId("parent-balance-pay")).toBeVisible();
  });

  test("money is said once: an open balance never also renders a payment action card", async ({
    page,
  }) => {
    // Enough for buildParentHomeModel to pick a "payment" primary action:
    // an active enrollment, a failed payment, and its still-open invoice.
    await stubGet(page, "**/api/v2/parent/enrollments", {
      enrollments: [
        {
          enrollment_id: "e1",
          student_id: "st-1",
          student_name: "Ava Kim",
          session_id: "sess-1",
          session_title: "Junior Beginners",
          status: "active",
          payment_mode: "monthly",
          subscription_status: null,
        },
      ],
    });
    await stubGet(page, "**/api/v2/parent/payments", {
      payments: [
        {
          payment_id: "pay-1",
          amount_cents: 12000,
          currency: "usd",
          status: "failed",
          refunded_cents: 0,
          created_at: "2026-09-01T12:00:00Z",
          session_id: "sess-1",
          invoice_id: "inv-1",
        },
      ],
    });
    await stubGet(page, "**/api/v2/parent/invoices", {
      invoices: [
        {
          invoice_id: "inv-1",
          period: "2026-09",
          status: "open",
          total_cents: 12000,
          balance_due_cents: 12000,
          currency: "usd",
          due_date: "2026-09-12",
          pdf_url: null,
          created_at: "2026-09-01T00:00:00Z",
        },
      ],
    });
    await stubHome(page, [AVA], {
      amount_due_cents: 12000,
      currency: "usd",
      due_date: "2026-09-12",
      open_invoice_count: 1,
      payment_failed: false,
    });

    await page.goto("/parent/dashboard");

    await expect(page.getByTestId("parent-balance-banner")).toBeVisible();
    await expect(page.getByText("Payment needs attention")).toHaveCount(0);
    // The banner's Pay button is Home's only route to billing.
    await expect(
      page.getByTestId("parent-dashboard").locator('a[href="/parent/payments"]'),
    ).toHaveCount(1);
  });

  test("a parent with no children keeps the registration hero and shows no cards", async ({
    page,
  }) => {
    await stubHome(page, []);

    await page.goto("/parent/dashboard");

    await expect(page.getByRole("link", { name: "Register a child" })).toBeVisible();
    await expect(page.getByTestId("parent-child-cards")).toHaveCount(0);
    await expect(page.getByTestId("parent-balance-banner")).toHaveCount(0);
  });

  test("each card is a single link named for the child, and nothing overflows at 320px", async ({
    page,
  }) => {
    await stubHome(page, [AVA, BO]);
    await page.setViewportSize({ width: 320, height: 720 });

    await page.goto("/parent/dashboard");

    const card = page.getByTestId("parent-child-card-st-1");
    await expect(card).toBeVisible();
    // The whole card is the tap target: no nested interactive elements.
    expect(await card.locator("a, button, input, select").count()).toBe(0);
    await expect(card).toHaveAccessibleName(/Ava Kim/);
    await expect
      .poll(async () => (await card.boundingBox())?.height ?? 0)
      .toBeGreaterThanOrEqual(44);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("parent home — Progress deep link", () => {
  test("tapping a card opens that child's skill progress", async ({ page }) => {
    await stubParentShell(page);
    await stubHome(page, [AVA, BO]);

    await stubGet(page, "**/api/v2/parent/children", {
      children: [AVA, BO].map((child) => ({
        student_id: child.student_id,
        full_name: child.full_name,
        status: "active",
        active_session_count: 1,
        attended_count: 0,
        absent_count: 0,
      })),
    });
    await page.route("**/api/v2/parent/students/*/skill-progress*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const forBo = route.request().url().includes("st-2");
      return json(route, {
        passport: [
          {
            skill_id: forBo ? "sk-bo" : "sk-ava",
            level_id: "l1",
            program_id: "prog-1",
            skill_name: forBo ? "Bo's overhead clear" : "Ava's short serve",
            skill_description: "",
            sequence: 1,
            is_required: true,
            status: "PASSED",
            last_test_passed: true,
            last_tested_at: "2026-09-01T00:00:00Z",
            test_attempt_count: 1,
          },
        ],
      });
    });
    await stubGet(page, "**/api/v2/parent/students/*/certificates", { certificates: [] });
    await stubGet(page, "**/api/v2/parent/students/*/skill-updates", { updates: [] });
    await stubGet(page, "**/api/v2/parent/students/*/practice-resources", { resources: [] });

    await page.goto("/parent/dashboard");
    await page.getByTestId("parent-child-card-st-2").click();

    await expect(page).toHaveURL(/\/parent\/progress\?child=st-2/);
    await expect(page.getByTestId("parent-progress")).toBeVisible();
    // The tab strip opened on the child the parent tapped, not on the first.
    await expect(page.getByText("Bo's overhead clear")).toBeVisible();
  });
});
