import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ME = {
  user_id: "user-admin-waivers-e2e",
  email: "admin@example.com",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

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

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubMe(page: Page) {
  await page.route("**/api/v2/me", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, ADMIN_ME);
  });
  await page.route("**/api/v2/me/memberships", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
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
    });
  });
}

async function stubAdminShell(page: Page) {
  await stubMe(page);
  await page.route("**/api/v2/admin/academy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      academy_id: "academy-e2e",
      display_name: "Rally Academy",
      timezone: "America/Chicago",
      contact_email: null,
      contact_phone: null,
      hours_text: null,
      address: null,
      logo_url: null,
      brand_color: null,
    });
  });
  // Issue #842: AdminLayout now feeds the Inbox nav badge from this endpoint
  // on every admin page, so every shell stub must cover it.
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
}

async function stubWaiverTemplates(page: Page) {
  await page.route("**/api/v2/admin/waivers/templates*", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, { templates: [] });
  });
}

/**
 * Settings overhaul Phase 3 PR 10: the waiver management UI now embeds in
 * Settings -> Family policies, which also mounts the self-service policy and
 * departure-policy (Holds) cards. Both are stubbed here so navigating to
 * that tab does not leave those cards stuck loading or erroring.
 */
async function stubFamilyPoliciesSiblingCards(page: Page) {
  await page.route("**/api/v2/admin/self-service/policy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      absence_notice_min_hours: 2,
      makeup_expiry_days: 30,
      makeup_requires_notice: true,
      cancellation_minimum_notice_days: 7,
      cancellation_fee_cents: 0,
      cancellation_effective_timing: "end_of_period",
      can_report_absence: true,
      can_request_makeup: true,
      can_request_pause: true,
      can_request_cancel: true,
      can_claim_waitlist_offer: true,
      payment_instructions: "",
      welcome_email_absence_policy_default: "",
    });
  });
  await page.route("**/api/v2/admin/enrollment/departure-policy", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return fulfillJson(route, {
      max_hold_days: 60,
      hold_reclaim_policy: "longest_held",
      drop_default_outcome: "no_credit_mid_month",
      delete_enrollment_requires_owner: true,
    });
  });
}

test.describe("admin waivers", () => {
  test("renders BFF summary counts and waiver student rows", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const requests: string[] = [];
    await stubAdminShell(page);
    await stubWaiverTemplates(page);
    await stubFamilyPoliciesSiblingCards(page);
    await page.route("**/api/v2/admin/waivers*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      requests.push(route.request().url());
      return fulfillJson(route, {
        summary: {
          signed_current: 12,
          pending_signature: 2,
          expiring_30d: 1,
          outdated_version: 3,
          active_students: 18,
          adoption_rate: 0.67,
        },
        current_waiver: {
          title: "Liability and media release",
          version: "v3.1",
          description: "Current academy waiver text supplied by the admin BFF.",
          effective_at: "2024-01-01T00:00:00Z",
          last_edited_at: "2024-02-14T00:00:00Z",
          signed_count: 12,
          total_count: 18,
          adoption_rate: 0.67,
        },
        waivers: [
          {
            waiver_id: "waiver-signed",
            student_id: "student-1",
            student_name: "Aarav Sharma",
            parent_id: "parent-1",
            parent_name: "Rohan Sharma",
            parent_email: "rohan@example.com",
            status: "signed",
            version: "v3.1",
            signed_at: "2024-02-12T12:00:00Z",
            method: "E-sign",
            expires_at: "2027-02-12T12:00:00Z",
          },
          {
            waiver_id: "waiver-pending",
            student_id: "student-2",
            student_name: "Vivaan Bhat",
            parent_id: "parent-2",
            parent_name: "Lakshmi Bhat",
            parent_email: "lakshmi@example.com",
            status: "pending",
            version: "v3.1",
            signed_at: null,
            method: null,
            expires_at: null,
          },
        ],
      });
    });

    await page.goto("/admin/settings?panel=family-policies");

    await expect(page.getByTestId("admin-waivers")).toBeVisible();
    await expect(page.getByText("Signed current")).toBeVisible();
    await expect(page.getByText("67% of active students").first()).toBeVisible();
    await expect(page.getByText("Pending signature")).toBeVisible();
    await expect(page.getByText("Expiring 30d")).toBeVisible();
    await expect(page.getByText("Outdated version")).toBeVisible();
    await expect(page.getByText("Liability and media release")).toBeVisible();

    const signedRow = page.getByTestId("admin-waivers-row-waiver-signed");
    await expect(signedRow).toContainText("Aarav Sharma");
    await expect(signedRow).toContainText("Rohan Sharma");
    await expect(signedRow).toContainText("v3.1");
    await expect(signedRow).toContainText("SIGNED");

    const pendingRow = page.getByTestId("admin-waivers-row-waiver-pending");
    await expect(pendingRow).toContainText("Vivaan Bhat");
    await expect(pendingRow).toContainText("PENDING");
    expect(requests).toHaveLength(1);
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("lists several live waivers and assigns one to a program", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    let assignBody: Record<string, unknown> | null = null;
    await stubAdminShell(page);
    await stubFamilyPoliciesSiblingCards(page);
    await page.route(/\/api\/v2\/admin\/waivers(?:\?.*)?$/, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        summary: { signed_current: 0, pending_signature: 0, expiring_30d: 0, outdated_version: 0 },
        current_waiver: null,
        waivers: [],
      });
    });
    const template = (id: string, title: string, extra: Record<string, unknown>) => ({
      waiver_template_id: id,
      title,
      body: `${title} text`,
      status: "active",
      version: "1",
      content_hash: "h",
      effective_at: "2026-09-01T00:00:00Z",
      published_at: "2026-09-01T00:00:00Z",
      assigned_to_registration: false,
      assigned_at: null,
      updated_at: "2026-09-01T00:00:00Z",
      required: false,
      scope: "all",
      program_ids: [],
      ...extra,
    });
    await page.route("**/api/v2/admin/waivers/templates", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        templates: [
          template("wt-liability", "Liability waiver", {
            version: "3",
            required: true,
            assigned_to_registration: true,
          }),
          template("wt-photo", "Photo consent", {}),
        ],
        programs: [
          { program_id: "prog-juniors", name: "Juniors" },
          { program_id: "prog-adults", name: "Adults" },
        ],
      });
    });
    await page.route("**/api/v2/admin/waivers/templates/wt-photo/assignment", (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      assignBody = route.request().postDataJSON() as Record<string, unknown>;
      return fulfillJson(
        route,
        template("wt-photo", "Photo consent", {
          required: true,
          scope: "programs",
          program_ids: ["prog-juniors"],
        }),
      );
    });

    await page.goto("/admin/settings?panel=family-policies");

    await expect(page.getByTestId("admin-waiver-required-for-wt-liability")).toContainText(
      "Required for: All families",
    );
    await expect(page.getByTestId("admin-waiver-required-for-wt-photo")).toContainText(
      "Required for: Not required",
    );
    await expect(page.getByTestId("admin-waiver-template-row-wt-liability")).toContainText("v3");
    await expect(page.getByTestId("admin-waiver-template-row-wt-liability")).toContainText("LIVE");

    await page.getByTestId("admin-waiver-assign-button-wt-photo").click();
    await page.getByTestId("admin-waiver-assign-choice-wt-photo-programs").check();
    await expect(page.getByTestId("admin-waiver-assign-save-wt-photo")).toBeDisabled();
    await page.getByTestId("admin-waiver-assign-program-wt-photo-prog-juniors").check();
    await page.getByTestId("admin-waiver-assign-save-wt-photo").click();

    await expect.poll(() => assignBody).toEqual({
      required: true,
      scope: "programs",
      program_ids: ["prog-juniors"],
    });
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("shows a truthful empty state when the BFF returns no waiver rows", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await stubWaiverTemplates(page);
    await stubFamilyPoliciesSiblingCards(page);
    await page.route("**/api/v2/admin/waivers*", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
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
      });
    });

    await page.goto("/admin/settings?panel=family-policies");
    await expect(page.getByTestId("admin-waivers-empty")).toContainText("No waiver rows returned.");
    await expect(page.getByText("Current waiver details are not available yet.")).toBeVisible();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("renders signed waiver artifact and share references", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/waivers/signatures/ws-1", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        signature_id: "ws-1",
        student_name: "Aarav Sharma",
        parent_name: "Rohan Sharma",
        parent_email: "rohan@example.com",
        signed_at: "2026-05-01T12:00:00Z",
        signer_name: "Rohan Sharma",
        signer_email: "rohan@example.com",
        waiver_title: "Annual waiver",
        waiver_version: "2026.1",
        template_reference: "wt-2026",
        content_hash: "hash-current",
        artifact_reference: "wa_ws-1",
        share_link_reference: "wsl_non_guessable_token_for_test",
        artifact_status: "stored",
        share_status: "available",
        gap_note: "Signed waiver artifact metadata is stored and an authorized share link is active.",
      });
    });

    await page.goto("/admin/waivers/signatures/ws-1");

    await expect(page.getByTestId("admin-signed-waiver-detail")).toBeVisible();
    await expect(page.getByText("Aarav Sharma")).toBeVisible();
    await expect(page.locator("dd").filter({ hasText: /^Stored$/ })).toBeVisible();
    await expect(page.locator("dd").filter({ hasText: /^Available$/ })).toBeVisible();
    await expect(page.getByText("wa_ws-1")).toBeVisible();
    await expect(page.getByText("wsl_non_guessable_token_for_test")).toBeVisible();
    expect(errors, `App console errors: ${errors.join("\n")}`).toEqual([]);
  });

  test("points the detail page at the Assign control in Family policies", async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const legacyAssignRequests: string[] = [];
    await stubAdminShell(page);
    await page.route("**/api/v2/admin/waivers/wt-2026", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return fulfillJson(route, {
        waiver_id: "wt-2026",
        title: "BLNO Liability Waiver",
        version: "1.0",
        body: "Parent agrees to academy safety rules.",
        content_hash: "hash-current",
        effective_at: "2026-05-26T00:00:00Z",
        status: "active",
        assigned_to_registration: false,
        assigned_at: null,
        artifact_status: "unavailable",
        share_status: "unavailable",
        gap_note: "Signed PDF artifact/share links are not implemented yet.",
      });
    });
    // The old one-waiver button is gone; nothing on the page should call it.
    await page.route("**/api/v2/admin/waivers/templates/wt-2026/assign-registration", (route) => {
      legacyAssignRequests.push(route.request().url());
      return route.abort();
    });

    await page.goto("/admin/waivers/wt-2026");

    await expect(page.getByTestId("admin-waiver-template-detail")).toBeVisible();
    await expect(page.getByRole("button", { name: "Require for registration" })).toHaveCount(0);
    const link = page.getByTestId("admin-waiver-detail-assign-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/admin/settings?panel=family-policies");
    expect(legacyAssignRequests).toHaveLength(0);
    expect(
      errors.filter((message) => !message.includes("500 (Internal Server Error)")),
      `App console errors: ${errors.join("\n")}`,
    ).toEqual([]);
  });
});
