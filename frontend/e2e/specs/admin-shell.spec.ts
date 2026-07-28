import { test, expect, type Page, type Route } from "@playwright/test";

import { openAdminNav } from "../helpers/nav";

const ADMIN_ME = {
  user_id: "user-admin-e2e",
  email: "admin@example.com",
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
] as const;

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

async function stubMemberships(page: Page, body = SINGLE_MEMBERSHIP) {
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, body);
  });
}

async function stubAdminBff(page: Page, memberships = SINGLE_MEMBERSHIP) {
  await stubMe(page, ADMIN_ME);
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
  await page.route("**/api/v2/coach/today*", (route) =>
    fulfillJson(route, { date: "2026-05-20", sessions: [] }),
  );
}

async function stubParentBff(page: Page) {
  await stubMe(page, PARENT_ME);
  await page.route("**/api/v2/parent/payments*", (route) =>
    fulfillJson(route, { payments: [] }),
  );
}

async function expectShellLogout(
  page: Page,
  path: string,
  readyTestId: string,
  stubBff: (page: Page) => Promise<void>,
) {
  await stubBff(page);
  await page.goto(path);
  await expect(page.getByTestId(readyTestId)).toBeVisible();
  const logout = page.getByTestId("persona-logout-button");
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
    await expect(page.getByTestId("tenant-switcher-single")).toContainText(
      "Academy E2E",
      {
        timeout: 10_000,
      },
    );
    const nav = await openAdminNav(page);
    await expect(nav.getByText("Academy E2E")).toBeVisible();
    await expect(nav.getByText("admin@example.com")).toBeVisible();
    await expect(nav.getByText("Admin", { exact: true })).toBeVisible();
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

    const switcherButton = page.getByTestId("tenant-switcher-button");
    await expect(switcherButton).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("tenant-switcher-single")).toHaveCount(0);
    await expect(switcherButton).toContainText("Academy E2E");

    await switcherButton.click();
    const menu = page.getByTestId("tenant-switcher-menu");
    await expect(menu).toBeVisible();
    await expect(
      page.getByTestId("tenant-switcher-option-academy-e2e"),
    ).toContainText("ACTIVE");
    await expect(
      page.getByTestId("tenant-switcher-option-academy-e2e-2"),
    ).toContainText("Academy E2E Two");

    await page.getByTestId("tenant-switcher-option-academy-e2e-2").click();
    await expect(menu).toBeHidden();

    // Re-open and confirm the ACTIVE marker moved to the newly selected
    // academy — the switcher pill label itself is driven by a separate
    // `/admin/academy` query stubbed statically in this spec.
    await switcherButton.click();
    await expect(menu).toBeVisible();
    await expect(
      page.getByTestId("tenant-switcher-option-academy-e2e-2"),
    ).toContainText("ACTIVE");
    await expect(
      page.getByTestId("tenant-switcher-option-academy-e2e"),
    ).not.toContainText("ACTIVE");

    expect(
      errors,
      `App console errors on multi-academy switcher: ${errors.join("\n")}`,
    ).toEqual([]);
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
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page);
      await page.goto(route.href);
      await expect(page.getByTestId(route.testid)).toBeVisible({
        timeout: 15000,
      });
      expect(
        errors,
        `App console errors on ${route.href}: ${errors.join("\n")}`,
      ).toEqual([]);
    });
  }

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
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    expect(
      errors,
      `Console errors on session detail: ${errors.join("\n")}`,
    ).toEqual([]);
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

  test("admin, coach, and parent shells expose logout", async ({ page }) => {
    await expectShellLogout(page, "/admin", "admin-dashboard", stubAdminBff);
    await expectShellLogout(page, "/coach/today", "coach-today", stubCoachBff);
    await expectShellLogout(page, "/parent/dashboard", "parent-dashboard", stubParentBff);
  });
});
