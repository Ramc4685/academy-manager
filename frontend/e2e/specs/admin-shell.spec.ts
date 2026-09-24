import { test, expect, type Page, type Route } from "@playwright/test";

import { billingRulesFixture } from "../fixtures/billing-rules";
import { openAdminNav } from "../helpers/nav";
import {
  clickRowAction,
  expectRowActionAvailable,
  rowActionControl,
} from "../helpers/row-actions";
import {
  stubCoachMessages,
  stubParentMessages,
} from "../fixtures/saas-stubs";
import { stubFamilyIndex } from "../fixtures/family-index";

// Every pre-split admin was granted `owner` by migration 0165, so the default
// admin fixture is an owner: it exercises the full shell (money nav, revenue,
// governance actions). ADMIN_ONLY_ME is an admin invited after the split.
const ADMIN_ME = {
  user_id: "user-admin-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin", "owner"],
};

const ADMIN_ONLY_ME = {
  user_id: "user-ops-e2e",
  email: "ops@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const COACH_ME = {
  user_id: "coach-e2e",
  email: "coach@example.com",
  academy_id: "academy-e2e",
  roles: ["coach"],
};

const PARENT_ME = {
  user_id: "parent-e2e",
  email: "parent@example.com",
  academy_id: "academy-e2e",
  roles: ["parent"],
};

/**
 * An empty Month close payload. Route stubs must name
 * `/api/v2/admin/reports/month-close` explicitly: a `*` glob stops at `/`, so
 * `admin/reports*` does NOT match it (lesson from the payments buckets spec).
 */
const MONTH_CLOSE_EMPTY = {
  generated_at: "2026-09-30T14:00:00Z",
  timezone: "America/Chicago",
  period: "2026-09",
  invoices: {
    generated: 0,
    emailed: 0,
    autopay_notices: 0,
    not_sent: 0,
    voided: 0,
    voided_cents: 0,
    void_reasons: [],
  },
  money: {
    billed_cents: 0,
    collected_cents: 0,
    outstanding_cents: 0,
    collection_rate: null,
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
  tuition_discounts: { gross_cents: 0, discount_cents: 0, net_cents: 0, by_category: [] },
  warnings: [],
};

const REPORTS_DASHBOARD_EMPTY = {
  period: "2026-05",
  cash_collected_cents: 0,
  outstanding_dues_cents: 0,
  attendance: {
    present_count: 0,
    recorded_count: 0,
    attendance_rate: null,
    empty: true,
  },
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
  expenses: {
    total_cents: 0,
    by_category: [],
  },
  collections_risk: {
    overdue_family_count: 0,
    overdue_cents: 0,
    failed_payment_count: 0,
    partial_payment_count: 0,
    aging_buckets: [],
  },
  profit_and_loss: {
    revenue_cents: 0,
    coach_payroll_cents: null,
    rent_cents: 0,
    misc_expenses_cents: 0,
    net_profit_cents: null,
    profit_margin: null,
  },
  payroll: {
    estimated_cents: null,
    approved_cents: null,
    paid_cents: null,
    unpaid_cents: null,
    blocked_by: "No generated payout periods for this month.",
  },
  empty_states: [],
};

const ADMIN_ROUTES = [
  { href: "/admin", testid: "admin-dashboard" },
  { href: "/admin/sessions", testid: "admin-sessions" },
  { href: "/admin/students", testid: "admin-students" },
  { href: "/admin/users", testid: "admin-users" },
  { href: "/admin/inbox", testid: "admin-inbox" },
  { href: "/admin/inbox?tab=registrations", testid: "admin-registrations-tab" },
  { href: "/admin/inbox?tab=waitlist", testid: "admin-waitlist-tab" },
  { href: "/admin/inbox?tab=level-ups", testid: "admin-level-up-queue-tab" },
  { href: "/admin/inbox?tab=pauses", testid: "admin-pause-requests" },
  { href: "/admin/payments", testid: "admin-payments" },
  { href: "/admin/reports/session-economics", testid: "admin-session-economics" },
  { href: "/admin/reports", testid: "admin-month-close" },
  { href: "/admin/coach-payslip", testid: "admin-coach-payslip" },
  { href: "/admin/expenses", testid: "admin-expenses" },
  { href: "/admin/payouts", testid: "admin-payouts" },
  { href: "/admin/audit-logs", testid: "admin-audit-logs" },
  { href: "/admin/messages", testid: "admin-messages" },
  { href: "/admin/waivers", testid: "admin-waivers" },
] as const;

const SETTINGS_PANELS = [
  { key: "academy", label: "Academy", testid: "admin-settings-academy" },
  { key: "billing-rules", label: "Billing rules", testid: "admin-settings-billing-rules" },
  { key: "gateway", label: "Gateway", testid: "admin-settings-gateway" },
  { key: "notify", label: "Notify", testid: "admin-settings-notify" },
  { key: "roles", label: "Roles", testid: "admin-settings-roles" },
  { key: "branding", label: "Branding", testid: "admin-settings-branding" },
  { key: "data", label: "Data", testid: "admin-settings-data" },
  {
    key: "session-types",
    label: "Session types",
    testid: "admin-settings-session-types",
  },
  { key: "public-page", label: "Public page", testid: "admin-settings-public-page" },
] as const;

const SESSION_TYPE_E2E = {
  session_type_id: "st-e2e",
  name: "Monthly Unlimited",
  description: "All weekday squads",
  price_cents: 12000,
  billing_period: "monthly",
  overage_rate_cents: 1500,
  is_active: true,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
} as const;

/** Soft-deleted: only returned when the panel asks for include_archived=true. */
const ARCHIVED_SESSION_TYPE_E2E = {
  session_type_id: "st-e2e-archived",
  name: "Retired Saturday Squad",
  description: null,
  price_cents: 8000,
  billing_period: "monthly",
  overage_rate_cents: null,
  is_active: false,
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
} as const;

const SESSION_DETAIL_E2E = {
  session_id: "some-session-id",
  coach_id: "coach-e2e",
  coach_name: "Coach E2E",
  title: "Session E2E",
  location: "Court 1",
  start_at: "2099-01-01T10:00:00Z",
  end_at: "2099-01-01T11:00:00Z",
  days_of_week: [],
  start_time: null,
  end_time: null,
  timezone: "UTC",
  capacity: 10,
  amount_cents: 10000,
  status: "scheduled",
  enrolled_count: 0,
  waitlist_count: 0,
} as const;

// Same row with `days_of_week` deliberately ABSENT — not `[]`. Session documents
// predate the field, and `hasRecurringSchedule` read `.length` off it unguarded,
// so one missing key took the whole page to the error boundary. `[]` does NOT
// exercise that branch, so this fixture exists to keep the `?.` honest.
const SESSION_NO_DAYS_E2E = {
  session_id: "no-days-session-id",
  coach_id: "coach-e2e",
  coach_name: "Coach E2E",
  title: "Legacy No Days",
  location: "Court 9",
  start_at: "2099-01-01T10:00:00Z",
  end_at: "2099-01-01T11:00:00Z",
  start_time: null,
  end_time: null,
  timezone: "UTC",
  capacity: 10,
  amount_cents: 10000,
  status: "scheduled",
  enrolled_count: 0,
  waitlist_count: 0,
} as const;

const BENIGN_PATTERNS: RegExp[] = [
  /Download the React DevTools/i,
  /Fast Refresh/i,
  /HMR/i,
  /webpack-internal/i,
];

function isBenign(message: string): boolean {
  return BENIGN_PATTERNS.some((re) => re.test(message));
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && !isBenign(msg.text())) {
      errors.push(msg.text());
    }
  });
  return errors;
}

/**
 * The Families view reads the family index (`/admin/families` and its
 * summary) and, for the bulk invite, `/admin/billing/setup`; the catch-all
 * `{}` stub has neither `families` nor `rows`. The redirect specs that land
 * on Families stub an empty index explicitly.
 */
async function stubEmptyFamilies(page: Page) {
  await stubFamilyIndex(page, { families: [] });
  await page.route("**/api/v2/admin/billing/setup*", (route) =>
    fulfillJson(route, {
      rows: [],
      summary: {
        families_total: 0,
        families_registered: 0,
        families_no_card: 0,
        outstanding_total_cents: 0,
      },
      next_cursor: null,
    }),
  );
}

function fulfillJson(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubMe(page: Page, body = ADMIN_ME) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, body);
  });
}

const SINGLE_MEMBERSHIP = {
  memberships: [
    {
      academy_id: "academy-e2e",
      academy_name: "Academy E2E",
      academy_slug: "academy-e2e",
      roles: ["admin"],
      status: "active",
      is_default: true,
    },
  ],
  active_academy_id: "academy-e2e",
};

const MULTI_MEMBERSHIP = {
  memberships: [
    {
      academy_id: "academy-e2e",
      academy_name: "Academy E2E",
      academy_slug: "academy-e2e",
      roles: ["admin"],
      status: "active",
      is_default: true,
    },
    {
      academy_id: "academy-e2e-2",
      academy_name: "Academy E2E Two",
      academy_slug: "academy-e2e-2",
      roles: ["admin"],
      status: "active",
      is_default: false,
    },
  ],
  active_academy_id: "academy-e2e",
};

const OWNER_MEMBERSHIP = {
  memberships: MULTI_MEMBERSHIP.memberships.map((m) => ({
    ...m,
    roles: ["admin", "owner"],
  })),
  active_academy_id: "academy-e2e",
};

async function stubMemberships(page: Page, body = SINGLE_MEMBERSHIP) {
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, body);
  });
}

async function stubAdminBff(
  page: Page,
  memberships = SINGLE_MEMBERSHIP,
  me: typeof ADMIN_ME = ADMIN_ME,
) {
  await stubMe(page, me);
  await stubMemberships(page, memberships);
  // Catch-all FIRST. Playwright route handlers match in LIFO order
  // (later-registered = higher priority), so registering this first means
  // the specific stubs below override it. Keeps any new admin endpoint
  // that the spec hasn't explicitly stubbed from returning {} and
  // crashing pages that expect a known shape.
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
  await page.route("**/api/v2/admin/sessions*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { sessions: [] });
  });
  await page.route("**/api/v2/admin/users*", (route) => {
    if (route.request().method() === "PATCH") {
      return fulfillJson(route, {
        user_id: "coach-e2e",
        email: "coach@example.com",
        display_name: "Coach E2E",
        role: "admin",
        status: "active",
      });
    }
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      users: [
        {
          user_id: "coach-e2e",
          email: "coach@example.com",
          display_name: "Coach E2E",
          role: "coach",
          status: "active",
        },
      ],
    });
  });
  await page.route("**/api/v2/admin/session-types*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    // Mirrors the backend: archived rows only when include_archived is set.
    const includeArchived =
      new URL(route.request().url()).searchParams.get("include_archived") === "true";
    return fulfillJson(route, {
      session_types: includeArchived
        ? [SESSION_TYPE_E2E, ARCHIVED_SESSION_TYPE_E2E]
        : [SESSION_TYPE_E2E],
    });
  });
  await page.route("**/api/v2/admin/students*", (route) =>
    fulfillJson(route, { students: [] }),
  );
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/registrations*", (route) =>
    fulfillJson(route, { registrations: [] }),
  );
  await page.route("**/api/v2/admin/payments*", (route) =>
    fulfillJson(route, { payments: [] }),
  );
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [] }),
  );
  await page.route("**/api/v2/admin/waivers*", (route) =>
    fulfillJson(route, {
      summary: {
        signed_current: 0,
        pending_signature: 0,
        expiring_30d: 0,
        outdated_version: 0,
        active_students: 0,
        adoption_rate: null,
      },
      current_waiver: null,
      waivers: [],
    }),
  );
  await page.route("**/api/v2/admin/waitlist", (route) =>
    fulfillJson(route, { total_waitlisted: 0, sessions: [] }),
  );
  await page.route("**/api/v2/admin/level-up-queue*", (route) =>
    fulfillJson(route, { queue: [] }),
  );
  await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
    fulfillJson(route, {
      items: [
        {
          attention_id: "waiver-status",
          kind: "waivers",
          title: "Waivers need review",
          detail: "2 pending, 1 outdated.",
          severity: "medium",
          href: "/admin/waivers",
          count: 3,
        },
      ],
    }),
  );
  await page.route("**/api/v2/admin/pause-requests*", (route) =>
    fulfillJson(route, { requests: [] }),
  );
  await page.route("**/api/v2/admin/audit-logs*", (route) =>
    fulfillJson(route, { logs: [] }),
  );
  const financeBff = "**/api/v2/admin/" + "finance/";
  await page.route(`${financeBff}payouts*`, (route) =>
    fulfillJson(route, { payouts: [] }),
  );
  await page.route(`${financeBff}expenses*`, (route) =>
    fulfillJson(route, { expenses: [] }),
  );
  await page.route(`${financeBff}revenue*`, (route) =>
    fulfillJson(route, { by_month: {} }),
  );
  await page.route("**/api/v2/admin/reports/month-close*", (route) =>
    fulfillJson(route, MONTH_CLOSE_EMPTY),
  );
  await page.route("**/api/v2/admin/reports/dashboard*", (route) =>
    fulfillJson(route, REPORTS_DASHBOARD_EMPTY),
  );
  await page.route("**/api/v2/admin/reports/session-economics*", (route) =>
    fulfillJson(route, {
      period: "2026-05",
      summary: {
        expected_revenue_cents: 0,
        paid_cents: 0,
        unpaid_cents: 0,
        coach_payroll_cents: 0,
        rent_cents: 0,
        other_expenses_cents: 0,
        expected_profit_cents: 0,
        profit_margin: null,
      },
      sessions: [],
      empty_states: [],
    }),
  );
  await page.route("**/api/v2/admin/reports/enrollment-funnel*", (route) =>
    fulfillJson(route, {
      leads: 0,
      applied: 0,
      assessed: 0,
      confirmed: 0,
      dropped: 0,
      total_applications: 0,
      conversion_rate: 0,
      period: null,
    }),
  );
  await page.route("**/api/v2/admin/reports/attendance-trends*", (route) =>
    fulfillJson(route, { periods: [], overall_completion_rate: 0 }),
  );
  await page.route("**/api/v2/admin/reports/coach-utilization*", (route) =>
    fulfillJson(route, { coaches: [], periods: [], total_payout_minor: 0 }),
  );
  await page.route(/\/api\/v2\/admin\/academy\/gateway(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      stripe_connected: false,
      stripe_account_id_masked: null,
      manual_methods: ["cash", "check"],
    }),
  );
  await page.route(/\/api\/v2\/admin\/academy\/fees(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      late_fee_cents: null,
      grace_days: null,
    }),
  );
  await page.route(/\/api\/v2\/admin\/billing\/rules(?:\?.*)?$/, (route) =>
    fulfillJson(route, billingRulesFixture()),
  );
  await page.route(
    /\/api\/v2\/admin\/academy\/notifications(?:\?.*)?$/,
    (route) =>
      fulfillJson(route, {
        daily_digest_to_admin: false,
      }),
  );
  await page.route(/\/api\/v2\/admin\/academy(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Academy E2E",
      timezone: "UTC",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
    }),
  );
}

async function stubCoachBff(page: Page) {
  await stubMe(page, COACH_ME);
  await stubCoachMessages(page);
  await page.route("**/api/v2/coach/today*", (route) =>
    fulfillJson(route, { date: "2026-05-20", sessions: [] }),
  );
}

async function stubParentBff(page: Page) {
  await stubMe(page, PARENT_ME);
  await stubParentMessages(page);
  await page.route("**/api/v2/parent/payments*", (route) =>
    fulfillJson(route, { payments: [] }),
  );
}

async function expectShellLogout(
  page: Page,
  path: string,
  readyTestId: string,
  stubBff: (page: Page) => Promise<void>,
  // The admin shell keeps its logout inside the nav surface (sidebar or
  // drawer), so it has to be revealed first; the other shells keep it in
  // the header.
  openNav = false,
) {
  await stubBff(page);
  await page.goto(path);
  await expect(page.getByTestId(readyTestId)).toBeVisible();
  const surface = openNav ? await openAdminNav(page) : page;
  const logout = surface.getByTestId("persona-logout-button");
  await expect(logout).toBeEnabled();
  await logout.scrollIntoViewIfNeeded();
  // WebKit mobile in CI is slow to settle the post-logout redirect; a 10s cap
  // flaked here. Wait up to the test-level budget instead of racing the click.
  await Promise.all([
    page.waitForURL(/\/login$/, { timeout: 20_000 }),
    logout.click(),
  ]);
}

test.describe("Rally admin shell", () => {
  test("admin shell uses academy display name without demo branding or internal IDs", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const nav = await openAdminNav(page);
    await expect(nav.getByTestId("tenant-switcher-single")).toContainText(
      "Academy E2E",
      {
        timeout: 10_000,
      },
    );
    await expect(nav.getByText("Academy E2E").first()).toBeVisible();
    await expect(nav.getByText("admin@example.com")).toBeVisible();
    // The default fixture holds the owner scope, so the pill reads Owner.
    await expect(nav.getByText("Owner", { exact: true })).toBeVisible();
    await expect(page.getByText("Rally Academy")).toHaveCount(0);
    await expect(page.getByText("COURT 7")).toHaveCount(0);
    await expect(page.getByText("academy-e2e")).toHaveCount(0);
    await expect(page.getByText("user-admin-e2e")).toHaveCount(0);
    expect(
      errors,
      `App console errors on shell branding: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("tenant switcher goes live and switches academy when the user has multiple memberships", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page, MULTI_MEMBERSHIP);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    let nav = await openAdminNav(page);
    const switcherButton = nav.getByTestId("tenant-switcher-button");
    await expect(switcherButton).toBeVisible({ timeout: 10_000 });
    await expect(nav.getByTestId("tenant-switcher-single")).toHaveCount(0);
    await expect(switcherButton).toContainText("Academy E2E");

    await switcherButton.click();
    const menu = nav.getByTestId("tenant-switcher-menu");
    await expect(menu).toBeVisible();
    await expect(
      nav.getByTestId("tenant-switcher-option-academy-e2e"),
    ).toContainText("ACTIVE");
    await expect(
      nav.getByTestId("tenant-switcher-option-academy-e2e-2"),
    ).toContainText("Academy E2E Two");

    await nav.getByTestId("tenant-switcher-option-academy-e2e-2").click();
    await expect(menu).toBeHidden();
    // Switching academies does not navigate, so the layout closes the
    // mobile drawer on the tenant-changed event instead. On desktop the
    // sidebar stays mounted and there is no drawer to hide.
    await expect(page.getByTestId("admin-mobile-drawer")).toBeHidden();

    // Re-open the nav (a no-op on desktop) and confirm the ACTIVE marker
    // moved to the newly selected academy — the switcher pill label itself
    // is driven by a separate `/admin/academy` query stubbed statically in
    // this spec.
    nav = await openAdminNav(page);
    await nav.getByTestId("tenant-switcher-button").click();
    await expect(nav.getByTestId("tenant-switcher-menu")).toBeVisible();
    await expect(
      nav.getByTestId("tenant-switcher-option-academy-e2e-2"),
    ).toContainText("ACTIVE");
    await expect(
      nav.getByTestId("tenant-switcher-option-academy-e2e"),
    ).not.toContainText("ACTIVE");

    expect(
      errors,
      `App console errors on multi-academy switcher: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("franchise rollup entry appears only for multi-academy owners", async ({
    page,
  }) => {
    await stubAdminBff(page, MULTI_MEMBERSHIP);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    // Admin in both academies, owner in neither — no rollup entry.
    const nav = await openAdminNav(page);
    await nav.getByTestId("tenant-switcher-button").click();
    await expect(nav.getByTestId("tenant-switcher-menu")).toBeVisible();
    await expect(
      nav.getByTestId("tenant-switcher-all-academies"),
    ).toHaveCount(0);
  });

  test("multi-academy owner can reach the franchise rollup from the switcher", async ({
    page,
  }) => {
    await stubAdminBff(page, OWNER_MEMBERSHIP);
    await page.route("**/api/v2/owner/rollup*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        academies: [
          {
            academy_id: "academy-e2e",
            academy_name: "Academy E2E",
            revenue_by_month: { "2026-07": 120_000 },
            collected_cents: 120_000,
            outstanding_cents: 5_000,
            outstanding_invoice_count: 2,
          },
          {
            academy_id: "academy-e2e-2",
            academy_name: "Academy E2E Two",
            revenue_by_month: { "2026-07": 80_000 },
            collected_cents: 80_000,
            outstanding_cents: 1_000,
            outstanding_invoice_count: 1,
          },
        ],
        totals: {
          academy_count: 2,
          revenue_by_month: { "2026-07": 200_000 },
          collected_cents: 200_000,
          outstanding_cents: 6_000,
          outstanding_invoice_count: 3,
        },
      });
    });

    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    const nav = await openAdminNav(page);
    await nav.getByTestId("tenant-switcher-button").click();
    const entry = nav.getByTestId("tenant-switcher-all-academies");
    await expect(entry).toBeVisible();
    await entry.click();

    // First navigation to /owner triggers a cold dev-server compile that can
    // exceed the default 5s; nothing else visits this route to warm it.
    await expect(page).toHaveURL(/\/owner$/, { timeout: 20_000 });
    await expect(page.getByTestId("owner-rollup-totals")).toContainText("$2,000.00");
    await expect(
      page.getByTestId("owner-rollup-row-academy-e2e-2"),
    ).toContainText("Academy E2E Two");
  });

  test("admin navigation renders all nav groups, and mobile drawer closes", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const nav = await openAdminNav(page);
    // Six groups (sidebar regroup spec §2.1), in sidebar order.
    for (const group of ["TODAY", "CLASSES", "PEOPLE", "REACH", "MONEY", "ACADEMY"]) {
      await expect(nav.getByText(group, { exact: true })).toBeVisible();
    }
    await expect(nav.getByRole("link", { name: /waivers/i })).toBeVisible();
    // Only the mobile drawer has a close affordance — the desktop sidebar
    // is always visible and has nothing to close.
    const closeButton = page.getByLabel("Close menu");
    if (await closeButton.isVisible()) {
      await closeButton.click();
      await expect(nav).toBeHidden();
    }
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("dashboard renders real attention items from the BFF", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard-attention")).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Waivers need review/i }),
    ).toHaveAttribute("href", "/admin/waivers");
    expect(
      errors,
      `App console errors on dashboard attention: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("dashboard leads with Needs your attention, above the KPI strip", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const attention = page.getByTestId("admin-dashboard-attention");
    await expect(attention).toBeVisible();
    const sessionsTile = page.getByTestId("dashboard-tile-sessions");
    await expect(sessionsTile).toBeVisible();
    const attentionBox = await attention.boundingBox();
    const sessionsBox = await sessionsTile.boundingBox();
    expect(attentionBox).not.toBeNull();
    expect(sessionsBox).not.toBeNull();
    // The attention card must sit above (smaller y) the KPI strip — today the
    // KPI grid renders first, so this fails on unfixed code.
    expect(attentionBox!.y).toBeLessThan(sessionsBox!.y);
  });

  test("Sessions today tile links to /admin/sessions", async ({ page }) => {
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const link = page.locator('a[data-testid="dashboard-tile-sessions"]');
    await expect(link).toHaveAttribute("href", "/admin/sessions");
  });

  test("Inbox nav row shows the pending count from the queue endpoint", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/inbox/counts", (route) =>
      fulfillJson(route, { counts: { registrations: 4, waitlist: 3 }, total: 7 }),
    );
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const nav = await openAdminNav(page);
    await expect(nav.getByTestId("admin-nav-inbox")).toContainText("7");
  });

  test("Inbox nav row hides the badge when the queue is empty", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const nav = await openAdminNav(page);
    await expect(nav.getByTestId("admin-nav-inbox")).not.toContainText("0");
  });

  test("all nav groups are visible at 1280x900 without scrolling the sidebar", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    const lastRow = page.getByTestId("admin-nav-audit-logs");
    await expect(lastRow).toBeVisible();
    const box = await lastRow.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(900);
    const nav = page.locator('aside[aria-label="Admin navigation"] nav').first();
    const overflow = await nav.evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(overflow).toBeLessThanOrEqual(1);
  });

  for (const route of ADMIN_ROUTES) {
    test(`route ${route.href} mounts`, async ({ page }) => {
      // Even with a 15s budget these mounts intermittently blow their deadline
      // on webkit-mobile during full-suite runs; they pass in isolation in ~3s.
      // Same webkit-under-load pattern as "session detail page mounts" below.
      // /admin/reports (the heaviest page) still tripped 15s under the local
      // gate's full shard with failOnFlakyTests — 30s is the mount budget.
      test.slow();
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page);
      await page.goto(route.href);
      await expect(page.getByTestId(route.testid)).toBeVisible({
        timeout: 30000,
      });
      expect(
        errors,
        `App console errors on ${route.href}: ${errors.join("\n")}`,
      ).toEqual([]);
    });
  }


  test.describe("owner / admin split", () => {
    test("admin without the owner scope sees no money-governance nav, revenue, or owner-only pages", async ({
      page,
    }) => {
      test.slow();
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page, SINGLE_MEMBERSHIP, ADMIN_ONLY_ME);
      await page.goto("/admin");
      await expect(page.getByTestId("admin-dashboard")).toBeVisible();

      // Dashboard: operations tiles stay, revenue tile and chart are gone.
      await expect(page.getByText("Sessions today")).toBeVisible();
      await expect(page.getByTestId("admin-dashboard-revenue")).toHaveCount(0);
      await expect(page.getByTestId("admin-dashboard-revenue-chart")).toHaveCount(0);
      await expect(page.getByText("Revenue (month to date)")).toHaveCount(0);

      // Nav: owner-only items are not rendered; operations items are.
      const nav = await openAdminNav(page);
      await expect(nav.getByTestId("admin-nav-payments")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-expenses")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-month-close")).toHaveCount(0);
      await expect(nav.getByTestId("admin-nav-coach-payouts")).toHaveCount(0);
      await expect(nav.getByTestId("admin-nav-audit-logs")).toHaveCount(0);
      // Stripe plumbing became owner-only with the Billing Health trim.
      await expect(nav.getByTestId("admin-nav-billing-health")).toHaveCount(0);
      await expect(nav.getByText("Admin", { exact: true })).toBeVisible();
      await expect(nav.getByText("Owner", { exact: true })).toHaveCount(0);

      // Deep link to an owner-only page shows the panel, not the page. The
      // shell hard-navigates seconds after paint, which can abort `page.goto`
      // itself ("interrupted by another navigation"); the panel below is the
      // assertion, so the aborted navigation is expected rather than a failure.
      await page.goto("/admin/reports", { waitUntil: "commit" }).catch(() => undefined);
      // The shell either swaps in the Owner only panel or bounces the non-owner
      // back to /admin. Both mean "you do not get this page"; which one wins is
      // a race in the shell that predates Month close, and pinning the test to
      // the panel alone is what made it flaky. The assertion that matters —
      // the page itself never renders — is checked either way.
      await expect
        .poll(
          async () =>
            (await page.getByTestId("owner-only-panel").count()) > 0 ||
            new URL(page.url()).pathname === "/admin",
          { timeout: 30_000 },
        )
        .toBe(true);
      await expect(page.getByTestId("admin-month-close")).toHaveCount(0);

      // Billing Health too — its BFF 404s for a non-owner, so the page would
      // have nothing to show even without the panel. Same shell race as
      // /admin/reports above: arm for either outcome rather than pinning the
      // test to the panel, which is what made this flake on webkit.
      await page.goto("/admin/billing-health", { waitUntil: "commit" }).catch(() => undefined);
      await expect
        .poll(
          async () =>
            (await page.getByTestId("owner-only-panel").count()) > 0 ||
            new URL(page.url()).pathname === "/admin",
          { timeout: 30_000 },
        )
        .toBe(true);
      await expect(page.getByTestId("billing-health-page")).toHaveCount(0);

      // The Dues page is gone (#687), so there is no longer an owner-only
      // exception to check here. Chasing balances is Payments work, which
      // admins keep; the old bookmarks forward there, covered by UIC3.

      expect(
        errors,
        `App console errors on admin-only shell: ${errors.join("\n")}`,
      ).toEqual([]);
    });

    test("owner keeps the money-governance nav, revenue, and reports", async ({
      page,
    }) => {
      test.slow();
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page);
      await page.goto("/admin");
      await expect(page.getByTestId("admin-dashboard")).toBeVisible();
      await expect(page.getByTestId("admin-dashboard-revenue")).toBeVisible();
      await expect(page.getByTestId("admin-dashboard-revenue-chart")).toBeVisible();

      const nav = await openAdminNav(page);
      await expect(nav.getByTestId("admin-nav-month-close")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-coach-payouts")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-audit-logs")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-billing-health")).toBeVisible();

      await page.goto("/admin/reports");
      await expect(page.getByTestId("admin-month-close")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("owner-only-panel")).toHaveCount(0);

      expect(
        errors,
        `App console errors on owner shell: ${errors.join("\n")}`,
      ).toEqual([]);
    });

    test("admin without the owner scope cannot pick admin or owner when adding a user", async ({
      page,
    }) => {
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page, SINGLE_MEMBERSHIP, ADMIN_ONLY_ME);
      await page.goto("/admin/users/new");
      const roleSelect = page.getByTestId("new-user-role");
      await expect(roleSelect).toBeVisible();
      const options = await roleSelect.locator("option").allTextContents();
      // Operations roles only: assistant_coach is grantable by any admin.
      expect(options.sort()).toEqual(["Assistant coach", "Coach", "Parent"]);
      expect(
        errors,
        `App console errors on admin-only add user: ${errors.join("\n")}`,
      ).toEqual([]);
    });

    test("owner can pick every academy role when adding a user", async ({ page }) => {
      await stubAdminBff(page);
      await page.goto("/admin/users/new");
      const roleSelect = page.getByTestId("new-user-role");
      await expect(roleSelect).toBeVisible();
      const options = await roleSelect.locator("option").allTextContents();
      expect(options.sort()).toEqual(["Admin", "Assistant coach", "Coach", "Owner", "Parent"]);
    });

    test("admin without the owner scope sees no Billing rules or Gateway settings", async ({
      page,
    }) => {
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page, SINGLE_MEMBERSHIP, ADMIN_ONLY_ME);
      await page.goto("/admin/settings");
      await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
      await expect(page.getByRole("link", { name: "Billing rules", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Gateway", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Notify", exact: true })).toBeVisible();

      // A deep link to an owner-only panel shows the notice, not the form.
      // A retired deep link (?panel=fees) resolves to Billing rules, which is
      // still owner-only, so the notice shows rather than the form.
      await page.goto("/admin/settings?panel=fees");
      await expect(page.getByTestId("owner-only-panel")).toBeVisible();
      await expect(page.getByTestId("admin-settings-billing-rules")).toHaveCount(0);
      expect(
        errors,
        `App console errors on admin-only settings: ${errors.join("\n")}`,
      ).toEqual([]);
    });
  });

  test("coach payslip redirects into Payouts → Payslips tab (UIC4)", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/coach-payslip");
    await expect(page).toHaveURL(/\/admin\/payouts\?tab=payslips/, { timeout: 30_000 });
    await expect(page.getByTestId("admin-payouts")).toBeVisible();
    await expect(page.getByTestId("admin-coach-payslip")).toBeVisible();
    expect(
      errors,
      `App console errors on coach payslip redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("both dues bookmarks redirect to Payments (UIC3)", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // The destination's own rendering is covered by the ADMIN_ROUTES mount
    // loop; this asserts only that the old bookmarks still land somewhere real.
    // #689: both paths are static `next.config.ts` redirects now, not RSC
    // pages that render the whole `(admin)` layout before throwing the
    // redirect signal (which is what blew the Cloudflare Workers resource
    // ceiling in production). The browser follows the 308 inside the same
    // navigation, so `page.goto` resolves on Payments — there is no
    // "interrupted by another navigation" abort to swallow any more. 30s, not
    // the 5s default, because a cold `next dev` compile can outlast it.
    for (const bookmark of ["/admin/dues", "/admin/reports/dues"]) {
      await page.goto(bookmark);
      await expect(page).toHaveURL(/\/admin\/payments$/, { timeout: 30_000 });
    }
    expect(
      errors,
      `App console errors on dues redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  // #827: the old people bookmarks. Same #689 shape as the dues pair — they
  // used to render the `(admin)` layout just to throw the redirect signal.
  // Sidebar regroup PR 3: parents left the Staff list, so /admin/parents now
  // lands on Families; /admin/coaches still opens the Coaches pill.
  test("the parents and coaches bookmarks redirect to Families and Staff", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await stubEmptyFamilies(page);
    for (const [bookmark, landing] of [
      ["/admin/parents", /\/admin\/families\?view=families$/],
      ["/admin/coaches", /\/admin\/users\?role=coach$/],
    ] as const) {
      await page.goto(bookmark);
      await expect(page).toHaveURL(landing, { timeout: 30_000 });
    }
    expect(
      errors,
      `App console errors on people redirects: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/session-economics redirects into Reports → Session economics (UIC3)", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // Same redirect race as the dues bookmark above.
    const landedEconomics = page.waitForURL(/\/admin\/reports\/session-economics$/, {
      timeout: 30_000,
    });
    await page.goto("/admin/session-economics", { waitUntil: "commit" }).catch(() => undefined);
    await landedEconomics;
    expect(
      errors,
      `App console errors on session economics redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/coaches redirects into the Users directory on the coach tab", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // Arm before navigating: the redirect fires during load and can abort
    // `page.goto` itself, and the 5s expect default is shorter than a cold
    // compile — the same race #683 armed for the other bookmark redirects.
    const landed = page.waitForURL(/\/admin\/users\?role=coach$/, { timeout: 30_000 });
    await page.goto("/admin/coaches", { waitUntil: "commit" }).catch(() => undefined);
    await landed;
    await expect(page.getByTestId("admin-users")).toBeVisible();
    // The coach engagement strip only renders while the Coaches tab is active.
    await expect(page.getByTestId("coach-engagement-stats")).toBeVisible();
    expect(
      errors,
      `App console errors on /admin/coaches redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/parents redirects to Families (sidebar regroup PR 3)", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await stubEmptyFamilies(page);
    // Arm before navigating: the redirect fires during load and can abort
    // `page.goto` itself, and the 5s expect default is shorter than a cold
    // compile — the same race #683 armed for the other bookmark redirects.
    const landed = page.waitForURL(/\/admin\/families\?view=families$/, {
      timeout: 30_000,
    });
    await page.goto("/admin/parents", { waitUntil: "commit" }).catch(() => undefined);
    await landed;
    await expect(page.getByTestId("admin-families")).toBeVisible();
    await expect(page.getByTestId("admin-users")).toHaveCount(0);
    expect(
      errors,
      `App console errors on /admin/parents redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  // A browser that cached the old 308 still lands on `/admin/users?role=parent`;
  // nothing server-side can clear that, so the URL stays a working parent list
  // with a banner pointing at Families and no pill selected (spec §3.1).
  test("/admin/users?role=parent still lists parents behind a Families banner", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const seen: string[] = [];
    await page.route("**/api/v2/admin/users?*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      seen.push(url.search);
      return fulfillJson(route, {
        users:
          url.searchParams.get("role") === "parent"
            ? [
                {
                  user_id: "parent-e2e",
                  email: "parent@example.com",
                  display_name: "Parent E2E",
                  role: "parent",
                  roles: ["parent"],
                  status: "active",
                },
              ]
            : [],
      });
    });
    await page.goto("/admin/users?role=parent");
    await expect(page.getByTestId("admin-users")).toBeVisible();
    await expect(page.getByTestId("admin-users-parents-banner")).toContainText("Families");
    await expect(page.getByTestId("admin-users-row-parent-e2e")).toBeVisible();
    // The banner replaces a pill: no Parents pill exists any more.
    await expect(page.getByTestId("admin-users-filter-parent")).toHaveCount(0);
    for (const pill of ["all", "coach", "assistant_coach", "admin"]) {
      await expect(page.getByTestId(`admin-users-filter-${pill}`)).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    }
    // The parent list is asked for as-is, never with the staff exclusion.
    expect(seen.some((q) => q.includes("role=parent"))).toBe(true);
    expect(seen.some((q) => q.includes("exclude_role"))).toBe(false);
    expect(
      errors,
      `App console errors on /admin/users?role=parent: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("Staff lists coaches and admins only, and keeps a coach who is also a parent", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const STAFF = [
      { user_id: "coach-e2e", email: "coach@example.com", display_name: "Coach E2E", role: "coach", roles: ["coach"], status: "active" },
      { user_id: "coach-parent-e2e", email: "both@example.com", display_name: "Coach And Parent", role: "parent", roles: ["parent", "coach"], status: "active" },
      { user_id: "parent-e2e", email: "parent@example.com", display_name: "Parent Only", role: "parent", roles: ["parent"], status: "active" },
    ];
    const queries: string[] = [];
    await page.route("**/api/v2/admin/users?*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      queries.push(url.search);
      // Mirror the BFF (#918): exclude_role=parent drops parent-only accounts.
      const excludeParentOnly = url.searchParams.get("exclude_role") === "parent";
      return fulfillJson(route, {
        users: excludeParentOnly
          ? STAFF.filter((user) => user.roles.some((r) => r !== "parent"))
          : STAFF,
      });
    });
    await page.goto("/admin/users");
    await expect(page.getByTestId("admin-users")).toBeVisible();
    await expect(page.getByTestId("admin-users-filter-all")).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("admin-users-filter-all")).toContainText("All staff");
    await expect(page.getByTestId("admin-users-row-coach-e2e")).toBeVisible();
    await expect(page.getByTestId("admin-users-row-coach-parent-e2e")).toBeVisible();
    await expect(page.getByTestId("admin-users-row-parent-e2e")).toHaveCount(0);
    await expect(page.getByTestId("admin-users-parents-link")).toHaveAttribute(
      "href",
      "/admin/families",
    );
    await expect(page.getByTestId("admin-users-parents-banner")).toHaveCount(0);
    expect(queries.some((q) => q.includes("exclude_role=parent"))).toBe(true);
    // The nav row is relabelled but keeps its id, so the testid survives.
    const nav = await openAdminNav(page);
    await expect(nav.getByTestId("admin-nav-users")).toContainText("Staff");
    await expect(nav.getByTestId("admin-nav-users")).not.toContainText("Users");
    expect(
      errors,
      `App console errors on /admin/users: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("pause requests identify parent, student, and session", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/pause-requests*", (route) =>
      fulfillJson(route, {
        requests: [
          {
            pause_request_id: "pause-1",
            parent_id: "parent-1",
            parent_name: "Abhishek Ajithkumar",
            parent_email: "abhishek@example.com",
            enrollment_id: "enr-1",
            student_id: "student-1",
            student_name: "Aadhya Abhishek",
            session_id: "session-1",
            session_title: "Junior Foundations",
            session_location: "Court 2",
            session_start_at: "2026-06-04T23:00:00Z",
            session_end_at: "2026-06-05T00:00:00Z",
            period: "2026-07",
            pause_kind: "fixed",
            resume_on: "2026-07-15",
            reason: "Summer travel",
            status: "pending",
            created_at: "2026-06-03T10:00:00Z",
            decided_at: null,
            decided_by: null,
          },
        ],
      }),
    );

    // Old URL now redirects into Inbox → Pauses tab (#776 merged Admissions +
    // Requests into one Inbox); bookmarks keep working.
    await page.goto("/admin/pause-requests");
    await expect(page).toHaveURL(/\/admin\/inbox\?tab=pauses/, { timeout: 30_000 });
    const row = page.getByTestId("admin-pause-requests-row-pause-1");
    await expect(row).toContainText("Abhishek Ajithkumar");
    await expect(row).toContainText("Student: Aadhya Abhishek");
    await expect(row).toContainText("Junior Foundations");
    await expect(row).toContainText("Court 2");
    await expect(row).toContainText("Resume Jul 15, 2026");
    await expect(row).toContainText("Summer travel");
    // #860: every decision fact is on the row — and the enrollment id is not.
    // On a phone the sticky action cell used to cover the session, dates and
    // reason; Decline/Approve now live behind the row's 44px actions menu,
    // which `rowActionControl` finds on either layout.
    await expect(row).not.toContainText("enr-1");
    const approve = await rowActionControl(page, {
      rowTestId: "admin-pause-requests-row-pause-1",
      actionsTestId: "admin-pause-requests-actions-pause-1",
      label: "Approve",
    });
    await expect(approve).toBeVisible();
    expect(
      errors,
      `App console errors on pause requests details: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("waitlist rows name the parent instead of printing a parent id", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/waitlist", (route) =>
      fulfillJson(route, {
        total_waitlisted: 1,
        sessions: [
          {
            session_id: "session-1",
            title: "Junior Foundations",
            location: "Court 2",
            start_at: "2026-06-04T23:00:00Z",
            capacity: 8,
            enrolled_count: 8,
            waitlist_count: 1,
            entries: [
              {
                waitlist_id: "wait-1",
                session_id: "session-1",
                student_id: "student-1",
                parent_id: "68b0f2c1a0b1c2d3e4f50011",
                parent_name: "Abhishek Ajithkumar",
                full_name: "Aadhya Abhishek",
                status: "waiting",
                position: 1,
                joined_at: "2026-06-01T10:00:00Z",
                added_at: "2026-06-01T10:00:00Z",
              },
            ],
          },
        ],
      }),
    );

    await page.goto("/admin/inbox?tab=waitlist");
    const row = page.getByTestId("admin-waitlist-row-wait-1");
    await expect(row).toContainText("Aadhya Abhishek");
    await expect(row).toContainText("Abhishek Ajithkumar");
    // #860: the raw Mongo id an admin can do nothing with.
    await expect(row).not.toContainText("68b0f2c1a0b1c2d3e4f50011");
    expect(errors, `App console errors on waitlist: ${errors.join("\n")}`).toEqual([]);
  });

  test("absence rows say which class and date was missed", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/self-service/absences*", (route) =>
      fulfillJson(route, {
        absences: [
          {
            notice_id: "notice-1",
            student_id: "student-1",
            occurrence_id: "occ-7f3a9c",
            session_id: "session-1",
            submitted_by: "parent-1",
            submitted_at: "2026-06-01T10:00:00Z",
            notice_window_met: true,
            student_full_name: "Aadhya Abhishek",
            recorded_by_admin: false,
            occurrence_session_title: "Junior Foundations",
            occurrence_start_at: "2026-06-04T23:00:00Z",
          },
        ],
      }),
    );

    await page.goto("/admin/inbox?tab=absences");
    const row = page.getByTestId("admin-absences-row-notice-1");
    await expect(row).toContainText("Aadhya Abhishek");
    // #860: the row carried only an occurrence id before, so it showed neither.
    await expect(row).toContainText("Junior Foundations");
    await expect(row).not.toContainText("occ-7f3a9c");
    expect(errors, `App console errors on absences: ${errors.join("\n")}`).toEqual([]);
  });

  test("payments renders legacy paid and waived statuses without crashing", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/payments*", (route) =>
      fulfillJson(route, {
        payments: [
          {
            payment_id: "legacy-paid",
            parent_id: "parent-1",
            student_id: "student-1",
            student_name: "Alice Chen",
            enrollment_id: "enrollment-1",
            session_id: "session-1",
            period: "2026-05",
            amount_cents: 12000,
            discount_cents: 0,
            final_amount_cents: 12000,
            amount_received_cents: 12000,
            paid_amount_cents: 12000,
            balance_due_cents: 0,
            overpayment_credit_cents: 0,
            currency: "usd",
            status: "paid",
            refunded_cents: 0,
            invoice_number: null,
            payment_method: "cash",
            stripe_linked: false,
            created_at: "2026-05-01T12:00:00Z",
          },
          {
            payment_id: "legacy-waived",
            parent_id: "parent-2",
            student_id: "student-2",
            student_name: "Bob Rao",
            enrollment_id: "enrollment-2",
            session_id: "session-1",
            period: "2026-05",
            amount_cents: 12000,
            discount_cents: 12000,
            final_amount_cents: 0,
            amount_received_cents: 0,
            paid_amount_cents: 0,
            balance_due_cents: 0,
            overpayment_credit_cents: 0,
            currency: "usd",
            status: "waived",
            refunded_cents: 0,
            invoice_number: null,
            payment_method: null,
            stripe_linked: false,
            created_at: "2026-05-02T12:00:00Z",
          },
        ],
      }),
    );

    await page.goto("/admin/payments?tab=invoices");

    await expect(page.getByTestId("payment-row-legacy-paid")).toBeVisible();
    await expect(
      // Exact, like the VOID assertion below: `getByText` matches a
      // case-insensitive SUBSTRING, so a loose "PAID" also matches the phone
      // row's "· paid $120.00" line (#857).
      page.getByTestId("payment-row-legacy-paid").getByText("PAID", { exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("payment-row-legacy-waived")).toBeVisible();
    await expect(
      page.getByTestId("payment-row-legacy-waived").getByText("VOID", { exact: true }),
    ).toBeVisible();
    expect(
      errors,
      `Console errors on legacy payment statuses: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("settings defaults to academy and each panel tab updates the URL", async ({
    page,
  }) => {
    test.slow();
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/settings");
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    await expect(page).toHaveURL(/\/admin\/settings\?panel=academy$/);

    for (const panel of SETTINGS_PANELS.filter(
      (panel) => panel.key !== "academy",
    )) {
      const tab = page.getByRole("link", { name: panel.label, exact: true });
      await tab.evaluate((element) =>
        element.scrollIntoView({ block: "nearest", inline: "center" }),
      );
      await Promise.all([
        page.waitForURL(new RegExp(`panel=${panel.key}`)),
        tab.click(),
      ]);
      await expect(tab).toHaveAttribute("aria-current", "page");
      await expect(page.getByTestId(panel.testid)).toBeVisible();
    }
    expect(
      errors,
      `App console errors on settings: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("settings warns before a tab switch discards unsaved edits", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/settings?panel=academy");
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();

    const displayName = page.getByLabel("Display name");
    // Wait for the loaded value first: filling before the academy read
    // resolves races the panel's seed and leaves a merged value (flaked in CI).
    await expect(displayName).toHaveValue("Academy E2E");
    await displayName.fill("Rally Academy Edited");

    // #893: the guard is the Rally dialog now, not `window.confirm`, so a
    // native dialog arriving here would be a regression, not the prompt.
    const nativeDialogs: string[] = [];
    page.on("dialog", async (dialog) => {
      nativeDialogs.push(dialog.message());
      await dialog.dismiss();
    });
    const guard = page.getByTestId("confirm-action-dialog");

    const notifyTab = page.getByRole("link", { name: "Notify", exact: true });
    await notifyTab.click();
    await expect(guard).toBeVisible();
    await expect(page.getByTestId("unsaved-changes-warning")).toBeVisible();

    // Stay: the panel stays put and the typed value survives.
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).toHaveURL(/panel=academy/);
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    await expect(displayName).toHaveValue("Rally Academy Edited");

    await notifyTab.click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/panel=notify/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
    await expect(page.getByTestId("admin-settings-notify")).toBeVisible();
    expect(nativeDialogs).toEqual([]);
    expect(
      errors,
      `App console errors on the settings dirty guard: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("settings warns before the shell nav discards unsaved edits", async ({
    page,
  }) => {
    // #893: #863's guard only intercepted the tab strip's own links, so
    // leaving through the sidebar (or the phone drawer) dropped the draft
    // with no prompt at all.
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/settings?panel=academy");
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();

    const displayName = page.getByLabel("Display name");
    // Wait for the loaded value before typing (see the tab-switch test).
    await expect(displayName).toHaveValue("Academy E2E");
    await displayName.fill("Rally Academy Edited");

    const drawer = page.getByTestId("admin-mobile-drawer");
    // The drawer closes itself on a nav click, so re-open it when the shell
    // is the phone one; on desktop the sidebar is always there.
    async function shellNav() {
      if (await drawer.isVisible()) return drawer;
      return openAdminNav(page);
    }

    const guard = page.getByTestId("confirm-action-dialog");
    await (await shellNav()).getByTestId("admin-nav-students").click();
    await expect(guard).toBeVisible();
    await expect(page.getByTestId("unsaved-changes-warning")).toBeVisible();

    // Stay: still on settings, with the edit intact.
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).toHaveURL(/\/admin\/settings\?panel=academy$/);
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    await expect(displayName).toHaveValue("Rally Academy Edited");
    expect(
      errors,
      `App console errors on the shell dirty guard: ${errors.join("\n")}`,
    ).toEqual([]);

    // Leaving on purpose still takes one confirm, not a fight.
    await (await shellNav()).getByTestId("admin-nav-students").click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/\/admin\/students/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
  });

  test("settings warns before a tab switch discards an in-progress role edit", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // The list stub's glob stops at the segment boundary, so the per-user
    // detail read needs its own route or it falls through to the catch-all.
    await page.route("**/api/v2/admin/users/coach-e2e", (route) =>
      fulfillJson(route, {
        user_id: "coach-e2e",
        email: "coach@example.com",
        display_name: "Coach E2E",
        role: "coach",
        status: "active",
        roles: ["coach"],
      }),
    );
    await page.goto("/admin/settings?panel=roles");
    await expect(page.getByTestId("admin-settings-roles")).toBeVisible();

    await page.getByRole("button", { name: "Edit roles" }).click();
    const parent = page.getByTestId("admin-settings-role-checkbox-coach-e2e-parent");
    await expect(parent).toBeVisible();
    await parent.check();

    const guard = page.getByTestId("confirm-action-dialog");
    const notifyTab = page.getByRole("link", { name: "Notify", exact: true });
    await notifyTab.click();
    await expect(guard).toBeVisible();

    // Stay: the editor stays open with the tick still applied.
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).toHaveURL(/panel=roles/);
    await expect(parent).toBeChecked();

    await notifyTab.click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/panel=notify/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
    await expect(page.getByTestId("admin-settings-notify")).toBeVisible();
    expect(
      errors,
      `App console errors on the roles dirty guard: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("student detail warns before a tab switch or a link discards an unsaved edit", async ({
    page,
  }) => {
    // UI-2: only Settings reported dirty state, so a typed student edit was
    // dropped by a tab switch (the tabs are buttons, not links) or any link.
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/students/student-guard-e2e", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        student_id: "student-guard-e2e",
        full_name: "Guard Student E2E",
        parent_id: "parent-guard-e2e",
        parent_name: "Guard Parent E2E",
        parent_email: "guard-parent@example.com",
        parent_phone: null,
        lifecycle: "active",
        active_session_count: 0,
        last_seen_at: null,
        attendance_rate: null,
        dues_status: "paid",
        date_of_birth: "2015-04-10",
        level: "beginner",
        notes: "",
        parent_details: null,
        previous_experience: "",
        medical_notes: "",
        emergency_contact_name: "",
        emergency_contact_phone: "",
        t_shirt_size: "",
        waiver_status: "signed",
        waiver_signed_at: null,
        waiver_version: null,
        recent_attendance: [],
        enrolled_sessions: [],
        past_enrollments: [],
        payment_history: [],
        current_payment: null,
      });
    });
    // The Training tab's skill pathway reads the program catalog; the shell
    // catch-all's `{}` has no `programs` key.
    await page.route("**/api/v2/admin/programs*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { programs: [] });
    });
    await page.route("**/api/v2/admin/enrollment/departure-policy", (route) =>
      fulfillJson(route, {
        max_hold_days: 30,
        hold_reclaim_policy: "longest_held",
        drop_default_outcome: "no_credit_mid_month",
        delete_enrollment_requires_owner: true,
      }),
    );
    const nativeDialogs: string[] = [];
    page.on("dialog", async (dialog) => {
      nativeDialogs.push(dialog.message());
      await dialog.dismiss();
    });

    await page.goto("/admin/students/student-guard-e2e");
    const fullName = page.getByLabel("Full name");
    await expect(fullName).toHaveValue("Guard Student E2E");

    // A clean form switches tabs with no prompt.
    const guard = page.getByTestId("confirm-action-dialog");
    const trainingTab = page.getByRole("tab", { name: "Training" });
    await trainingTab.click();
    await expect(page).toHaveURL(/tab=training/);
    await expect(guard).toHaveCount(0);
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(fullName).toHaveValue("Guard Student E2E");

    await fullName.fill("Guard Student Edited");

    // Keyboard: the tab is reachable and Enter opens the guard, focus moves
    // into the dialog, and Escape stays and hands focus back to the tab.
    await trainingTab.focus();
    await page.keyboard.press("Enter");
    await expect(guard).toBeVisible();
    await expect(page.getByTestId("unsaved-changes-warning")).toBeVisible();
    await expect
      .poll(() => guard.evaluate((el) => el.contains(document.activeElement)))
      .toBe(true);
    await page.keyboard.press("Escape");
    await expect(guard).toHaveCount(0);
    await expect(trainingTab).toBeFocused();
    await expect(page).not.toHaveURL(/tab=training/);
    await expect(fullName).toHaveValue("Guard Student Edited");

    // Stay keeps the tab and the typed value.
    await trainingTab.click();
    await expect(guard).toBeVisible();
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).not.toHaveURL(/tab=training/);
    await expect(fullName).toHaveValue("Guard Student Edited");

    // An in-app link is guarded too.
    await page.getByRole("link", { name: "All students" }).click();
    await expect(guard).toBeVisible();
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(page).toHaveURL(/\/admin\/students\/student-guard-e2e/);
    await expect(fullName).toHaveValue("Guard Student Edited");

    // Leaving on purpose takes one confirm.
    await trainingTab.click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/tab=training/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
    await expect(page.getByTestId("admin-student-training-tab")).toBeVisible();

    // Nothing is dirty any more: the next switch is immediate.
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(fullName).toHaveValue("Guard Student E2E");
    await expect(guard).toHaveCount(0);
    expect(nativeDialogs).toEqual([]);
    expect(
      errors,
      `App console errors on the student dirty guard: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("user detail warns before a link discards an unsaved profile edit", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    let saved: Record<string, unknown> | null = null;
    const staff = {
      user_id: "staff-guard-e2e",
      email: "staff-guard@example.com",
      display_name: "Guard Staff E2E",
      role: "admin",
      status: "active",
      roles: ["admin"],
      phone: null,
    };
    await page.route("**/api/v2/admin/users/staff-guard-e2e", (route) => {
      const method = route.request().method();
      if (method === "PATCH") {
        saved = route.request().postDataJSON() as Record<string, unknown>;
        return fulfillJson(route, { ...staff, ...saved });
      }
      if (method !== "GET") return route.fallback();
      return fulfillJson(route, staff);
    });

    await page.goto("/admin/users/staff-guard-e2e");
    const displayName = page.getByLabel("Display name");
    await expect(displayName).toHaveValue("Guard Staff E2E");
    await displayName.fill("Guard Staff Edited");

    const guard = page.getByTestId("confirm-action-dialog");
    const back = page.getByRole("link", { name: "All users" });
    await back.click();
    await expect(guard).toBeVisible();
    await expect(page.getByTestId("unsaved-changes-warning")).toBeVisible();
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).toHaveURL(/\/admin\/users\/staff-guard-e2e$/);
    await expect(displayName).toHaveValue("Guard Staff Edited");

    // A successful save is clean at once, even though the refetch still
    // returns the old name: the link leaves with no prompt.
    await page
      .getByTestId("admin-user-edit-form")
      .getByRole("button", { name: /^save changes$/i })
      .click();
    await expect.poll(() => saved).toMatchObject({ display_name: "Guard Staff Edited" });
    await expect(
      page.getByTestId("admin-user-edit-form").getByText("Saved", { exact: false }),
    ).toBeVisible();
    await Promise.all([page.waitForURL(/\/admin\/users$/), back.click()]);
    await expect(guard).toHaveCount(0);

    // Edit again and leave on purpose through the confirm.
    await page.goto("/admin/users/staff-guard-e2e");
    await expect(displayName).toHaveValue("Guard Staff E2E");
    await displayName.fill("Guard Staff Again");
    await back.click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/\/admin\/users$/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
    expect(
      errors,
      `App console errors on the user dirty guard: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("settings tabs keep 44px targets and the active tab in view at 400px", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await page.setViewportSize({ width: 400, height: 800 });
    await stubAdminBff(page);
    await page.goto("/admin/settings?panel=session-types");
    await expect(page.getByTestId("admin-settings-session-types")).toBeVisible();

    for (const panel of SETTINGS_PANELS) {
      const tab = page.getByRole("link", { name: panel.label, exact: true });
      const box = await tab.boundingBox();
      if (!box) throw new Error(`no bounding box for the ${panel.label} tab`);
      expect(box.height, `${panel.label} tap target height`).toBeGreaterThanOrEqual(44);
    }

    // Deep-linked: the strip scrolls the active tab into view by itself, with
    // no scrollIntoView() from the test.
    const active = page.getByRole("link", { name: "Session types", exact: true });
    await expect(active).toHaveAttribute("aria-current", "page");
    const activeBox = await active.boundingBox();
    if (!activeBox) throw new Error("no bounding box for the active tab");
    expect(activeBox.x, "active tab left edge").toBeGreaterThanOrEqual(0);
    expect(activeBox.x + activeBox.width, "active tab right edge").toBeLessThanOrEqual(400);
    expect(
      errors,
      `App console errors on the settings tab strip: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("session types panel lists the catalog and posts a new type", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const created: Array<Record<string, unknown>> = [];
    await page.route("**/api/v2/admin/session-types", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      created.push(route.request().postDataJSON());
      return fulfillJson(route, {
        ...SESSION_TYPE_E2E,
        session_type_id: "st-new",
        name: "Drop-in",
      });
    });

    await page.goto("/admin/settings?panel=session-types");
    await expect(page.getByTestId("admin-settings-session-types")).toBeVisible();
    await expect(page.getByTestId("session-type-row")).toHaveCount(1);
    // price_cents 12000 / overage 1500 must render as dollars, not raw cents.
    await expect(page.getByText("$120.00")).toBeVisible();
    await expect(page.getByText("$15.00")).toBeVisible();

    await page.getByTestId("session-type-new").click();
    await page.locator("#st-name").fill("Drop-in");
    await page.locator("#st-price").fill("25.50");
    await page.locator("#st-period").selectOption("per_session");
    await page.getByTestId("session-type-save").click();

    await expect.poll(() => created.length).toBe(1);
    expect(created[0]).toMatchObject({
      name: "Drop-in",
      price_cents: 2550,
      billing_period: "per_session",
    });
    expect(
      errors,
      `App console errors on session types: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("session types show-archived toggle lists archived rows and reactivates one", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const patched: Array<Record<string, unknown>> = [];
    await page.route("**/api/v2/admin/session-types/*", (route) => {
      if (route.request().method() !== "PATCH") return route.fallback();
      patched.push({
        url: route.request().url(),
        body: route.request().postDataJSON(),
      });
      return fulfillJson(route, { ...ARCHIVED_SESSION_TYPE_E2E, is_active: true });
    });

    await page.goto("/admin/settings?panel=session-types");
    // Archived rows are hidden by default.
    await expect(page.getByTestId("session-type-row")).toHaveCount(1);
    await expect(page.getByText("Retired Saturday Squad")).toHaveCount(0);

    await page.getByTestId("session-types-show-archived").check();
    await expect(page.getByTestId("session-type-row")).toHaveCount(2);
    const archivedRow = page
      .getByTestId("session-type-row")
      .filter({ hasText: "Retired Saturday Squad" });
    await expect(archivedRow).toHaveAttribute("data-archived", "true");
    await expect(archivedRow.getByText("ARCHIVED")).toBeVisible();

    // The active row keeps Archive; only the archived row offers Reactivate.
    await expect(page.getByTestId("session-type-reactivate")).toHaveCount(1);
    await archivedRow.getByTestId("session-type-reactivate").click();

    await expect.poll(() => patched.length).toBe(1);
    expect(patched[0].body).toEqual({ is_active: true });
    expect(String(patched[0].url)).toContain("st-e2e-archived");
    expect(
      errors,
      `App console errors on archived session types: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("session types archive confirm warns that enrollments keep billing", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.goto("/admin/settings?panel=session-types");
    await expect(page.getByTestId("session-type-row")).toHaveCount(1);

    await page.getByRole("button", { name: "Archive", exact: true }).click();
    await expect(
      page.getByText(/keep billing at their current price/i),
    ).toBeVisible();
    await expect(page.getByTestId("session-type-archive-confirm")).toBeVisible();
  });

  test("students search sends BFF query and renders returned rich fields", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const seenSearches: string[] = [];
    await page.route("**/api/v2/admin/students*", (route) => {
      const url = new URL(route.request().url());
      seenSearches.push(url.searchParams.get("search") ?? "");
      return fulfillJson(route, {
        students: [
          {
            student_id: "st-alice",
            full_name: "Alice Chen",
            parent_id: "parent-1",
            parent_name: "Maya Chen",
            parent_email: "maya@example.com",
            lifecycle: "active",
            active_session_count: 2,
            last_seen_at: "2026-05-17T12:00:00Z",
            attendance_rate: 0.85,
            dues_status: "due",
          },
        ],
        next_cursor: null,
      });
    });

    await page.goto("/admin/students");
    await page.getByPlaceholder("Search students or parents").fill("alice");

    await expect
      .poll(() => seenSearches, {
        message: "students search query should be sent",
      })
      .toContain("alice");
    const row = page.getByTestId("admin-students-row-st-alice");
    await expect(row.getByText("Alice Chen")).toBeVisible();
    await expect(row.getByText("85%")).toBeVisible();
    await expect(row.getByText("DUE")).toBeVisible();
    expect(
      errors,
      `Console errors on students search: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("students lifecycle filter resets pagination cursor", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const requests: Array<{ lifecycle: string; cursor: string }> = [];
    await page.route("**/api/v2/admin/students*", (route) => {
      const url = new URL(route.request().url());
      requests.push({
        lifecycle: url.searchParams.get("lifecycle") ?? "",
        cursor: url.searchParams.get("cursor") ?? "",
      });
      const cursor = url.searchParams.get("cursor");
      return fulfillJson(route, {
        students: [
          {
            student_id: cursor ? "st-page-2" : "st-page-1",
            full_name: cursor ? "Bob Rao" : "Alice Chen",
            parent_id: "parent-1",
            parent_name: "Maya Chen",
            parent_email: "maya@example.com",
            lifecycle: url.searchParams.get("lifecycle") || "active",
            active_session_count: 1,
            last_seen_at: null,
            attendance_rate: null,
            dues_status: "current",
          },
        ],
        next_cursor: cursor ? null : "next-cursor",
      });
    });

    await page.goto("/admin/students");
    await page.getByRole("button", { name: "Next page" }).click();
    await page.getByTestId("admin-students-filter-paused").click();

    await expect
      .poll(() =>
        requests.some((req) => req.lifecycle === "paused" && req.cursor === ""),
      )
      .toBe(true);
    expect(
      errors,
      `Console errors on students pagination: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("session detail page mounts", async ({ page }) => {
    // Mount regularly exceeds the default expect budget on webkit-mobile under
    // full-suite load (observed across unrelated branches and in CI).
    test.slow();
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    expect(
      errors,
      `Console errors on session detail: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("session detail shows coaching staff and the assistants editor saves", async ({
    page,
  }) => {
    test.slow();
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);

    // The assistants editor merges two role-filtered directory reads
    // (coach + assistant_coach); mirror the backend's `?role=` filter.
    const USERS = [
      { user_id: "coach-e2e", email: "coach@example.com", display_name: "Coach E2E", role: "coach", status: "active" },
      { user_id: "coach-2-e2e", email: "coach2@example.com", display_name: "Second Coach", role: "coach", status: "active" },
      { user_id: "asst-e2e", email: "helper@example.com", display_name: "Asha Assistant", role: "assistant_coach", status: "active" },
    ];
    await page.route("**/api/v2/admin/users*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const role = new URL(route.request().url()).searchParams.get("role");
      return fulfillJson(route, {
        users: role ? USERS.filter((user) => user.role === role) : USERS,
      });
    });

    let assistantIds = ["asst-e2e"];
    const nameOf = (id: string) => USERS.find((user) => user.user_id === id)?.display_name ?? id;
    const sessionBody = () => ({
      ...SESSION_DETAIL_E2E,
      assistant_coach_ids: assistantIds,
      assistant_coach_names: assistantIds.map(nameOf),
    });
    const puts: Array<Record<string, unknown>> = [];
    await page.route("**/api/v2/admin/sessions/*/assistants", (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const body = JSON.parse(route.request().postData() ?? "{}") as {
        assistant_coach_ids: string[];
      };
      puts.push(body);
      assistantIds = body.assistant_coach_ids;
      return fulfillJson(route, sessionBody());
    });
    await page.route("**/api/v2/admin/sessions/*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, sessionBody());
    });

    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByTestId("session-lead-coach")).toContainText("Coach E2E");
    await expect(page.getByTestId("session-assistants")).toContainText("Asha Assistant");

    await page.getByTestId("edit-assistants").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("assistant-option-asst-e2e")).toBeChecked();
    // The lead coach is never offered as their own assistant.
    await expect(dialog.getByTestId("assistant-option-coach-e2e")).toHaveCount(0);
    await dialog.getByTestId("assistant-option-coach-2-e2e").check();
    await dialog.getByRole("button", { name: "Save" }).click();

    await expect.poll(() => puts.length).toBe(1);
    expect(puts[0]).toEqual({
      assistant_coach_ids: ["asst-e2e", "coach-2-e2e"],
      reason: null,
    });
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByTestId("session-assistants")).toContainText("Second Coach");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    expect(
      errors,
      `Console errors on session assistants: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  // Regression for #503: `AddToRosterDialog` renders a custom `RallyModal`, not a
  // Radix `Dialog.Root`. An orphaned `Dialog.Close` inside it threw during render
  // and replaced the whole page with the app error boundary.
  test("add to roster dialog opens without crashing the page", async ({ page }) => {
    test.slow();
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // Override the empty-students stub so the StudentSelect branch renders.
    await page.route("**/api/v2/admin/students*", (route) =>
      fulfillJson(route, {
        students: [
          {
            student_id: "student-e2e-1",
            full_name: "Rory Roster",
            parent_id: "parent-e2e-1",
            parent_name: "Parent E2E",
            parent_email: "parent@example.com",
            lifecycle: "active",
            active_session_count: 1,
            active_session_total: 1,
            active_session_names: ["Session E2E"],
            last_seen_at: null,
            attendance_rate: null,
            dues_status: "current",
          },
        ],
      }),
    );
    // POST quote — stubAdminBff's catch-all is GET-only, so without this the
    // request falls through to the real network.
    await page.route("**/api/v2/admin/enrollments/quote", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      return fulfillJson(route, {
        snapshot_id: "snap-e2e",
        quote_expires_at: null,
        amount_due_cents: 5000,
        monthly_price_cents: 10000,
        billing_period: "2026-09",
        total_eligible_classes_this_month: 8,
        billable_remaining_classes_this_month: 4,
        formula: "prorated",
        included_occurrence_ids: [],
        excluded_occurrences: {},
        policy_version: "v1",
        settings_version: "v1",
        schedule_signature: null,
      });
    });

    // One roster row so RosterPanel renders its own LevelSelect. That page-level
    // combobox sits BEFORE the portalled dialog in the DOM, which is exactly why
    // the dialog's select must be located through the dialog and not by `.first()`.
    await page.route("**/api/v2/admin/sessions/*/enrollments", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        enrollments: [
          {
            enrollment_id: "enr-e2e-1",
            session_id: "some-session-id",
            student_id: "student-e2e-1",
            parent_id: "parent-e2e-1",
            full_name: "Rory Roster",
            status: "active",
            enrolled_at: "2026-01-01T00:00:00Z",
            dues_status: "current",
          },
        ],
      });
    });

    // The GET-only catch-all answers the session-detail fetch with `{}`; stub a
    // realistic row so the header renders the real session.
    await page.route("**/api/v2/admin/sessions/*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, SESSION_DETAIL_E2E);
    });

    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();

    await page.getByRole("button", { name: "Add to roster" }).click();

    // The dialog opened...
    await expect(page.getByRole("button", { name: "Enroll" })).toBeVisible();
    // ...and the page did NOT fall through to app/error.tsx.
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByText("Something went wrong")).toHaveCount(0);

    // Exercise the StudentSelect + quote banner branch.
    // Scoped to the dialog on purpose: `RallyModal` portals to the END of
    // <body>, so its select is the LAST combobox on the page, never the first.
    // `getByRole("combobox").first()` only worked while the roster stub was
    // empty and RosterPanel rendered no LevelSelect of its own.
    await page.getByRole("dialog").getByRole("combobox").selectOption("student-e2e-1");
    await expect(page.getByText("First month:")).toBeVisible();

    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
    expect(
      errors,
      `Console errors on add-to-roster: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  // Regression for #467: a failed session cancel was completely silent — the
  // mutation was fired with `.mutate()` and had no `onError`.
  test("failed session cancel surfaces an error", async ({ page }) => {
    test.slow();
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/sessions*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        sessions: [
          {
            session_id: "session-e2e-1",
            coach_id: "coach-e2e",
            coach_name: "Coach E2E",
            title: "Cancelable Session",
            location: "Court 1",
            start_at: "2099-01-01T10:00:00Z",
            end_at: "2099-01-01T11:00:00Z",
            days_of_week: [],
            start_time: null,
            end_time: null,
            timezone: "UTC",
            capacity: 10,
            amount_cents: 10000,
            status: "scheduled",
            enrolled_count: 2,
            waitlist_count: 0,
          },
        ],
      });
    });
    let failureMode: "reason" | "blank" = "reason";
    await page.route("**/api/v2/admin/sessions/*", (route) => {
      if (route.request().method() !== "DELETE") return route.fallback();
      return route.fulfill(
        failureMode === "reason"
          ? {
              status: 403,
              contentType: "application/json",
              body: JSON.stringify({ detail: "Not allowed to cancel this session." }),
            }
          : // Error envelope with a BLANK message — `makeError` copies it onto
            // the Error verbatim, so `err.message` is "". That is the payload
            // that used to render "Could not cancel session: Could not cancel
            // session." from a literal prefix plus the identical fallback.
            {
              status: 500,
              contentType: "application/json",
              body: JSON.stringify({ error: { code: "Internal", message: "" } }),
            },
      );
    });
    await page.goto("/admin/sessions");
    await expect(page.getByTestId("admin-sessions")).toBeVisible();
    // #838: the native confirm is gone; the Rally dialog's confirm is what
    // actually fires the DELETE. #847: on phone this button lives behind the
    // row's actions menu, so `clickRowAction` opens that first.
    await clickRowAction(page, {
      rowTitle: "Cancelable Session",
      directLabel: "Cancel session Cancelable Session",
      menuItemLabel: "Cancel session",
    });
    await page.getByTestId("confirm-action-submit").click();

    const banner = page.getByTestId("admin-sessions-cancel-error");
    await expect(banner).toBeVisible();
    // Assert the SERVER's reason, not the hardcoded prefix: "Could not cancel
    // session" is both the prefix and the generic fallback, so matching only
    // that cannot tell a surfaced reason from a swallowed one.
    await expect(banner.locator("p")).toHaveText(
      "Could not cancel session: Not allowed to cancel this session.",
    );

    // The cancel FAILED, so the row must still be there. Without this, a future
    // optimistic update that removed the row and showed the error would pass.
    await expect(page.getByText("Cancelable Session")).toBeVisible();
    await expectRowActionAvailable(page, {
      rowTitle: "Cancelable Session",
      directLabel: "Cancel session Cancelable Session",
      menuItemLabel: "Cancel session",
    });

    // Blank-message failure: exactly one "Could not cancel session".
    await banner.getByRole("button", { name: "Dismiss" }).click();
    await expect(banner).toBeHidden();
    failureMode = "blank";
    await clickRowAction(page, {
      rowTitle: "Cancelable Session",
      directLabel: "Cancel session Cancelable Session",
      menuItemLabel: "Cancel session",
    });
    await page.getByTestId("confirm-action-submit").click();
    await expect(banner.locator("p")).toHaveText("Could not cancel session.");
  });

  // #467 on the DETAIL page — the primary cancel entry point. Its banner had no
  // coverage at all: deleting the whole `onError` block left the suite green.
  test("failed session cancel surfaces an error on the detail page", async ({ page }) => {
    test.slow();
    await stubAdminBff(page);
    let failureMode: "reason" | "blank" = "reason";
    await page.route("**/api/v2/admin/sessions/*", (route) => {
      const method = route.request().method();
      if (method === "GET") return fulfillJson(route, SESSION_DETAIL_E2E);
      if (method !== "DELETE") return route.fallback();
      return route.fulfill(
        failureMode === "reason"
          ? {
              status: 403,
              contentType: "application/json",
              body: JSON.stringify({ detail: "Not allowed to cancel this session." }),
            }
          : {
              status: 500,
              contentType: "application/json",
              body: JSON.stringify({ error: { code: "Internal", message: "" } }),
            },
      );
    });
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    // #838: the page button opens the dialog; its confirm fires the DELETE.
    // The dialog's confirm shares the label, so it is reached by test id.
    await page.getByRole("button", { name: "Cancel session" }).click();
    await page.getByTestId("confirm-action-submit").click();

    const banner = page.getByTestId("admin-session-cancel-error");
    await expect(banner).toBeVisible();
    await expect(banner.locator("p")).toHaveText(
      "Could not cancel session: Not allowed to cancel this session.",
    );
    // A failed cancel must not navigate away to the list.
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();

    await banner.getByRole("button", { name: "Dismiss" }).click();
    await expect(banner).toBeHidden();
    failureMode = "blank";
    await page.getByRole("button", { name: "Cancel session" }).click();
    await page.getByTestId("confirm-action-submit").click();
    await expect(banner.locator("p")).toHaveText("Could not cancel session.");
  });

  // #503-class: a session payload with NO `days_of_week` key must not crash the
  // edit dialog (and with it the page) to the error boundary.
  test("session detail edit dialog survives a payload without days_of_week", async ({ page }) => {
    test.slow();
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/sessions/*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, SESSION_NO_DAYS_E2E);
    });

    await page.goto("/admin/sessions/no-days-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await page.getByRole("button", { name: "Edit session" }).click();

    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog").getByText("Edit session")).toBeVisible();
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
  });

  test("sessions list edit dialog survives a payload without days_of_week", async ({ page }) => {
    test.slow();
    await stubAdminBff(page);
    await page.route("**/api/v2/admin/sessions*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, { sessions: [SESSION_NO_DAYS_E2E] });
    });

    await page.goto("/admin/sessions");
    await expect(page.getByTestId("admin-sessions")).toBeVisible();
    // #847: on phone Edit lives behind the row's actions menu.
    await clickRowAction(page, {
      rowTitle: "Legacy No Days",
      directLabel: "Edit session Legacy No Days",
      menuItemLabel: "Edit",
    });

    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("dialog").getByText("Edit session")).toBeVisible();
    await expect(page.getByTestId("admin-sessions")).toBeVisible();
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
  });

  test("coach smoke route mounts", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubCoachBff(page);
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    expect(
      errors,
      `Console errors on coach route: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("parent smoke route mounts", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubParentBff(page);
    await page.goto("/parent/dashboard");
    await expect(page.getByTestId("parent-dashboard")).toBeVisible();
    expect(
      errors,
      `Console errors on parent route: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("admin topbar keeps account controls out of the header at every width", async ({
    page,
    isMobile,
  }) => {
    // Multi-membership so the tenant switcher is a live button, and an admin
    // user gets the Coach view, so the persona switcher renders too. Both
    // would appear in the topbar if the controls had not moved.
    await stubAdminBff(page, MULTI_MEMBERSHIP);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    if (isMobile) {
      await expect(page.getByTestId("admin-open-drawer")).toBeVisible();
      // Drawer closed: nothing in the DOM carries the switcher testids.
      await expect(page.getByTestId("persona-switcher-button")).toHaveCount(0);
      await expect(page.getByTestId("tenant-switcher-button")).toHaveCount(0);
      await expect(page.getByTestId("persona-logout-button")).toHaveCount(0);
    }
    // Sidebar on desktop, drawer on phones: the controls live there.
    const nav = await openAdminNav(page);
    await expect(nav.getByTestId("persona-switcher-button")).toBeVisible();
    await expect(nav.getByTestId("tenant-switcher-button")).toBeVisible({
      timeout: 10_000,
    });
    await expect(nav.getByTestId("persona-logout-button")).toBeVisible();
    // The topbar has none of them at any width (spec B2).
    const header = page.locator("header");
    await expect(header.getByTestId("persona-switcher-button")).toHaveCount(0);
    await expect(header.getByTestId("tenant-switcher-button")).toHaveCount(0);
    await expect(header.getByTestId("persona-logout-button")).toHaveCount(0);
  });

  test("coach session detail shows a back button that falls back to the parent route", async ({
    page,
    baseURL,
  }) => {
    await stubCoachBff(page);
    // A deep-linked PWA launch has history depth 1, so the button pushes the
    // nearest known parent route instead of calling history.back(). A
    // Playwright tab starts on about:blank and `page.goto` would add a
    // second entry, so replace that initial entry instead.
    const target = new URL("/coach/sessions/some-session-id", baseURL).toString();
    await page.evaluate((url) => window.location.replace(url), target);
    await page.waitForURL(target);
    expect(await page.evaluate(() => window.history.length)).toBe(1);
    await expect(page.getByText("Session not found.")).toBeVisible();
    const back = page.getByTestId("shell-back-button");
    await expect(back).toBeVisible();
    await back.click();
    await expect(page).toHaveURL(/\/coach\/sessions$/, { timeout: 20_000 });
  });

  test("coach top-level route shows no back button", async ({ page }) => {
    await stubCoachBff(page);
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    await expect(page.getByTestId("shell-back-button")).toHaveCount(0);
  });

  test("admin session detail shows the back button and the dashboard does not", async ({
    page,
  }) => {
    test.slow();
    await stubAdminBff(page);
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await expect(page.getByTestId("shell-back-button")).toBeVisible();

    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await expect(page.getByTestId("shell-back-button")).toHaveCount(0);
  });

  /**
   * Issue #896: `NavRow` is the row of BOTH nav surfaces, so the fix
   * (`min-h-touch lg:min-h-0`) has to be measured on both — a phone drawer
   * row must clear the 44px touch minimum, and the desktop sidebar must keep
   * the denser row #842 introduced to fit 17 rows above the 1280x900 fold.
   * The spec branches on which surface is actually on screen, exactly as
   * `openAdminNav` does, so it asserts the right thing in either project.
   */
  test("nav rows are touch-sized in the phone drawer and dense on desktop", async ({
    page,
  }) => {
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();

    const onPhone = await page.getByTestId("admin-open-drawer").isVisible();
    const nav = await openAdminNav(page);
    const rows = nav.locator('[data-testid^="admin-nav-"]');
    await expect(rows.first()).toBeVisible();
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);

    // Counts are stubbed empty, so no badge arrives later to change a row's
    // height; still settle on the first row's measured height before the
    // loop rather than measuring mid-layout.
    await expect
      .poll(async () => (await rows.first().boundingBox())?.height ?? 0)
      .toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const box = await rows.nth(index).boundingBox();
      expect(box, `nav row ${index} has no box`).not.toBeNull();
      const height = box?.height ?? 0;
      if (onPhone) {
        expect(height, `drawer row ${index} is under the 44px minimum`).toBeGreaterThanOrEqual(44);
      } else {
        expect(height, `sidebar row ${index} lost #842's density`).toBeLessThan(44);
      }
    }
  });

  test("admin, coach, and parent shells expose logout", async ({ context }) => {
    // One page per persona. The persona auth hook's `replaceLocation` arms a
    // 1s hard `window.location.replace("/login")` fallback; on WebKit that
    // timer from the previous persona's page interrupted the next persona's
    // `page.goto` ("interrupted by another navigation to /login", #650).
    for (const [path, readyTestId, stubBff, openNav] of [
      ["/admin", "admin-dashboard", stubAdminBff, true],
      ["/coach/today", "coach-today", stubCoachBff, false],
      ["/parent/dashboard", "parent-dashboard", stubParentBff, false],
    ] as const) {
      const personaPage = await context.newPage();
      try {
        await expectShellLogout(personaPage, path, readyTestId, stubBff, openNav);
      } finally {
        await personaPage.close();
      }
    }
  });
});
