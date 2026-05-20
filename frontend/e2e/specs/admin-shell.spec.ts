import { test, expect, type Page, type Route } from "@playwright/test";

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

const ADMIN_ROUTES = [
  { href: "/admin", testid: "admin-dashboard" },
  { href: "/admin/sessions", testid: "admin-sessions" },
  { href: "/admin/students", testid: "admin-students" },
  { href: "/admin/users", testid: "admin-users" },
  { href: "/admin/waitlist", testid: "admin-waitlist" },
  { href: "/admin/pause-requests", testid: "admin-pause-requests" },
  { href: "/admin/payments", testid: "admin-payments" },
  { href: "/admin/dues", testid: "admin-dues" },
  { href: "/admin/reports", testid: "admin-reports" },
  { href: "/admin/coach-payslip", testid: "admin-coach-payslip" },
  { href: "/admin/expenses", testid: "admin-expenses" },
  { href: "/admin/payouts", testid: "admin-payouts" },
  { href: "/admin/audit-logs", testid: "admin-audit-logs" },
  { href: "/admin/messages", testid: "admin-messages" },
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

async function stubAdminBff(page: Page) {
  await stubMe(page, ADMIN_ME);
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
    fulfillJson(route, { students: [] })
  );
  await page.route("**/api/v2/admin/payments*", (route) =>
    fulfillJson(route, { payments: [] })
  );
  await page.route("**/api/v2/admin/messages*", (route) =>
    fulfillJson(route, { messages: [] })
  );
  await page.route("**/api/v2/admin/pause-requests*", (route) =>
    fulfillJson(route, { requests: [] })
  );
  await page.route("**/api/v2/admin/audit-logs*", (route) =>
    fulfillJson(route, { logs: [] })
  );
  await page.route("**/api/v2/admin/dues-followup*", (route) =>
    fulfillJson(route, { parents: [] })
  );
  const financeBff = "**/api/v2/admin/" + "finance/";
  await page.route(`${financeBff}payouts*`, (route) =>
    fulfillJson(route, { payouts: [] })
  );
  await page.route(`${financeBff}expenses*`, (route) =>
    fulfillJson(route, { expenses: [] })
  );
  await page.route(`${financeBff}revenue*`, (route) =>
    fulfillJson(route, { by_month: {} })
  );
  await page.route(/\/api\/v2\/admin\/academy\/gateway(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      stripe_connected: false,
      stripe_account_id_masked: null,
      manual_methods: ["cash", "check"],
    })
  );
  await page.route(/\/api\/v2\/admin\/academy\/fees(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      default_monthly_cents: null,
      late_fee_cents: null,
      grace_days: null,
    })
  );
  await page.route(/\/api\/v2\/admin\/academy\/notifications(?:\?.*)?$/, (route) =>
    fulfillJson(route, {
      dues_reminders: false,
      attendance_alerts: false,
      daily_digest_to_admin: false,
    })
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
    })
  );
  await page.route("**/api/v2/admin/**", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {});
  });
}

async function stubCoachBff(page: Page) {
  await stubMe(page, COACH_ME);
  await page.route("**/api/v2/coach/today*", (route) =>
    fulfillJson(route, { date: "2026-05-20", sessions: [] })
  );
}

async function stubParentBff(page: Page) {
  await stubMe(page, PARENT_ME);
  await page.route("**/api/v2/parent/payments*", (route) =>
    fulfillJson(route, { payments: [] })
  );
}

test.describe("Rally admin shell", () => {
  test("mobile drawer opens, contains all nav groups, and closes", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin");
    await expect(page.getByTestId("admin-dashboard")).toBeVisible();
    await page.getByTestId("admin-open-drawer").click();
    const drawer = page.getByTestId("admin-mobile-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("WORK", { exact: true })).toBeVisible();
    await expect(drawer.getByText("MONEY", { exact: true })).toBeVisible();
    await expect(drawer.getByText("COMMS · OPS", { exact: true })).toBeVisible();
    await drawer.getByLabel("Close menu").click();
    await expect(drawer).toBeHidden();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  for (const route of ADMIN_ROUTES) {
    test(`route ${route.href} mounts`, async ({ page }) => {
      const errors = collectConsoleErrors(page);
      await stubAdminBff(page);
      await page.goto(route.href);
      await expect(page.getByTestId(route.testid)).toBeVisible({ timeout: 15000 });
      expect(errors, `App console errors on ${route.href}: ${errors.join("\n")}`).toEqual([]);
    });
  }

  test("settings defaults to academy and each panel tab updates the URL", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/settings");
    await expect(page.getByTestId("admin-settings-academy")).toBeVisible();
    await expect(page).toHaveURL(/\/admin\/settings\?panel=academy$/);

    for (const panel of SETTINGS_PANELS) {
      await page.getByRole("button", { name: panel.label }).click();
      await expect(page).toHaveURL(new RegExp(`panel=${panel.key}`));
      await expect(page.getByTestId(panel.testid)).toBeVisible();
    }
    expect(errors, `App console errors on settings: ${errors.join("\n")}`).toEqual([]);
  });

  test("session detail page mounts", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminBff(page);
    await page.goto("/admin/sessions/some-session-id");
    await expect(page.getByTestId("admin-session-detail")).toBeVisible();
    expect(errors, `Console errors on session detail: ${errors.join("\n")}`).toEqual([]);
  });

  test("coach smoke route mounts", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubCoachBff(page);
    await page.goto("/coach/today");
    await expect(page.getByTestId("coach-today")).toBeVisible();
    expect(errors, `Console errors on coach route: ${errors.join("\n")}`).toEqual([]);
  });

  test("parent smoke route mounts", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubParentBff(page);
    await page.goto("/parent/dashboard");
    await expect(page.getByTestId("parent-dashboard")).toBeVisible();
    expect(errors, `Console errors on parent route: ${errors.join("\n")}`).toEqual([]);
  });
});
