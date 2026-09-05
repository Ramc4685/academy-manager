import { test, expect, type Page, type Route } from "@playwright/test";

import { openAdminNav } from "../helpers/nav";
import {
  stubCoachMessages,
  stubParentMessages,
} from "../fixtures/saas-stubs";

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
  { href: "/admin/registrations", testid: "admin-registrations" },
  { href: "/admin/registrations?tab=waitlist", testid: "admin-waitlist-tab" },
  { href: "/admin/registrations?tab=level-ups", testid: "admin-level-up-queue-tab" },
  { href: "/admin/requests?tab=pauses", testid: "admin-pause-requests" },
  { href: "/admin/payments", testid: "admin-payments" },
  { href: "/admin/reports/dues", testid: "admin-dues" },
  { href: "/admin/reports/session-economics", testid: "admin-session-economics" },
  { href: "/admin/reports", testid: "admin-reports" },
  { href: "/admin/coach-payslip", testid: "admin-coach-payslip" },
  { href: "/admin/expenses", testid: "admin-expenses" },
  { href: "/admin/payouts", testid: "admin-payouts" },
  { href: "/admin/audit-logs", testid: "admin-audit-logs" },
  { href: "/admin/messages", testid: "admin-messages" },
  { href: "/admin/waivers", testid: "admin-waivers" },
] as const;

const SETTINGS_PANELS = [
  { key: "academy", label: "Academy", testid: "admin-settings-academy" },
  { key: "fees", label: "Fees", testid: "admin-settings-fees" },
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
  await page.route("**/api/v2/admin/dues-followup*", (route) =>
    fulfillJson(route, { parents: [] }),
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
      default_monthly_cents: null,
      late_fee_cents: null,
      grace_days: null,
    }),
  );
  await page.route(
    /\/api\/v2\/admin\/academy\/notifications(?:\?.*)?$/,
    (route) =>
      fulfillJson(route, {
        dues_reminders: false,
        attendance_alerts: false,
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
    await expect(nav.getByText("WORK", { exact: true })).toBeVisible();
    await expect(nav.getByText("MONEY", { exact: true })).toBeVisible();
    await expect(
      nav.getByText("COMMS · OPS", { exact: true }),
    ).toBeVisible();
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
      await expect(nav.getByTestId("admin-nav-reports")).toHaveCount(0);
      await expect(nav.getByTestId("admin-nav-coach-payouts")).toHaveCount(0);
      await expect(nav.getByTestId("admin-nav-audit-logs")).toHaveCount(0);
      await expect(nav.getByText("Admin", { exact: true })).toBeVisible();
      await expect(nav.getByText("Owner", { exact: true })).toHaveCount(0);

      // Deep link to an owner-only page shows the panel, not the page.
      await page.goto("/admin/reports");
      await expect(page.getByTestId("owner-only-panel")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("admin-reports")).toHaveCount(0);

      // Dues follow-up is operations work and stays open.
      await page.goto("/admin/reports/dues");
      await expect(page.getByTestId("admin-dues")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("owner-only-panel")).toHaveCount(0);

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
      await expect(nav.getByTestId("admin-nav-reports")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-coach-payouts")).toBeVisible();
      await expect(nav.getByTestId("admin-nav-audit-logs")).toBeVisible();

      await page.goto("/admin/reports");
      await expect(page.getByTestId("admin-reports")).toBeVisible({ timeout: 30_000 });
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
      expect(options.sort()).toEqual(["coach", "parent"]);
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
      expect(options.sort()).toEqual(["admin", "coach", "owner", "parent"]);
    });

    test("admin without the owner scope sees no Fees or Gateway settings", async ({
      page,
    }) => {
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page, SINGLE_MEMBERSHIP, ADMIN_ONLY_ME);
      await page.goto("/admin/settings");
      await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
      await expect(page.getByRole("link", { name: "Fees", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Gateway", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Notify", exact: true })).toBeVisible();

      // A deep link to an owner-only panel shows the notice, not the form.
      await page.goto("/admin/settings?panel=fees");
      await expect(page.getByTestId("owner-only-panel")).toBeVisible();
      await expect(page.getByTestId("admin-settings-fees")).toHaveCount(0);
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
    await expect(page).toHaveURL(/\/admin\/payouts\?tab=payslips/);
    await expect(page.getByTestId("admin-payouts")).toBeVisible();
    await expect(page.getByTestId("admin-coach-payslip")).toBeVisible();
    expect(
      errors,
      `App console errors on coach payslip redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/dues redirects into Reports → Dues follow-up (UIC3)", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    // The destination's own rendering is covered by the ADMIN_ROUTES mount
    // loop; this asserts only that the old bookmark still lands there.
    await page.goto("/admin/dues");
    await expect(page).toHaveURL(/\/admin\/reports\/dues$/);
    expect(
      errors,
      `App console errors on dues redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/session-economics redirects into Reports → Session economics (UIC3)", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/session-economics");
    await expect(page).toHaveURL(/\/admin\/reports\/session-economics$/);
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
    await page.goto("/admin/coaches");
    await expect(page).toHaveURL(/\/admin\/users\?role=coach$/);
    await expect(page.getByTestId("admin-users")).toBeVisible();
    // The coach engagement strip only renders while the Coaches tab is active.
    await expect(page.getByTestId("coach-engagement-stats")).toBeVisible();
    expect(
      errors,
      `App console errors on /admin/coaches redirect: ${errors.join("\n")}`,
    ).toEqual([]);
  });

  test("/admin/parents redirects into the Users directory on the parent tab", async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/parents");
    await expect(page).toHaveURL(/\/admin\/users\?role=parent$/);
    await expect(page.getByTestId("admin-users")).toBeVisible();
    // Parent tab must NOT show the coach-only engagement strip.
    await expect(page.getByTestId("coach-engagement-stats")).toHaveCount(0);
    expect(
      errors,
      `App console errors on /admin/parents redirect: ${errors.join("\n")}`,
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

    // Old URL now redirects into Requests → Pauses tab (UIC2); bookmarks keep working.
    await page.goto("/admin/pause-requests");
    await expect(page).toHaveURL(/\/admin\/requests\?tab=pauses/);
    const row = page.getByTestId("admin-pause-requests-row-pause-1");
    await expect(row).toContainText("Abhishek Ajithkumar");
    await expect(row).toContainText("Student: Aadhya Abhishek");
    await expect(row).toContainText("Junior Foundations");
    await expect(row).toContainText("Court 2");
    await expect(row).toContainText("Resume Jul 15, 2026");
    await expect(row).toContainText("Summer travel");
    expect(
      errors,
      `App console errors on pause requests details: ${errors.join("\n")}`,
    ).toEqual([]);
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

    await page.goto("/admin/payments");

    await expect(page.getByTestId("payment-row-legacy-paid")).toBeVisible();
    await expect(
      page.getByTestId("payment-row-legacy-paid").getByText("PAID"),
    ).toBeVisible();
    await expect(page.getByTestId("payment-row-legacy-waived")).toBeVisible();
    await expect(
      page.getByTestId("payment-row-legacy-waived").getByText("WAIVED"),
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
            status: "active",
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

  test("students status filter resets pagination cursor", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    const requests: Array<{ status: string; cursor: string }> = [];
    await page.route("**/api/v2/admin/students*", (route) => {
      const url = new URL(route.request().url());
      requests.push({
        status: url.searchParams.get("status") ?? "",
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
            status: url.searchParams.get("status") || "active",
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
    await page.getByRole("button", { name: /Paused/i }).click();

    await expect
      .poll(() =>
        requests.some((req) => req.status === "paused" && req.cursor === ""),
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
            status: "active",
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
    page.on("dialog", (dialog) => void dialog.accept());

    await page.goto("/admin/sessions");
    await expect(page.getByTestId("admin-sessions")).toBeVisible();
    await page.getByRole("button", { name: "Cancel session Cancelable Session" }).click();

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
    await expect(
      page.getByRole("button", { name: "Cancel session Cancelable Session" }),
    ).toBeVisible();

    // Blank-message failure: exactly one "Could not cancel session".
    await banner.getByRole("button", { name: "Dismiss" }).click();
    await expect(banner).toBeHidden();
    failureMode = "blank";
    await page.getByRole("button", { name: "Cancel session Cancelable Session" }).click();
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
    page.on("dialog", (dialog) => void dialog.accept());

    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    await page.getByRole("button", { name: "Cancel session" }).click();

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
    await page.getByRole("button", { name: "Edit session Legacy No Days" }).click();

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
