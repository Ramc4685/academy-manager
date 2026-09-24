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
import { familyIndexRow } from "../fixtures/family-index";

/**
 * People CRM family record page (engineering-spec §4, Lane A4): the tab shell
 * on /admin/families/[parentId], the Details tab, the child drawer
 * with shared coach notes, and the admin attendance correction's confirm step
 * and focus return. Every API is mocked; names are fake.
 */

const RECORD = {
  generated_at: "2026-09-23T15:00:00Z",
  family_id: "parent-1",
  family: familyIndexRow({
    family_id: "parent-1",
    parent_name: "Test Parent One",
    email: "parent.one@example.test",
    phone: "555-010-0001",
    stage: "active",
    children: [
      {
        student_id: "stu-a",
        name: "Kid Alpha",
        lifecycle: "active",
        lifecycle_as_of: null,
        classes: [{ session_id: "sess-sat", title: "Sat Beginners" }],
        matched: false,
      },
    ],
    money: {
      balance_cents: 7000,
      open_invoice_count: 1,
      overdue_invoice_count: 0,
      overdue_cents: 0,
      oldest_overdue_due_on: null,
      last_failed_payment_at: null,
    },
  }),
  money_visible: true,
  warnings: [],
};

const BILLING = {
  generated_at: "2026-09-23T15:00:00Z",
  timezone: "America/Chicago",
  today: "2026-09-23",
  parent: {
    parent_id: "parent-1",
    name: "Test Parent One",
    email: "parent.one@example.test",
    phone: "555-010-0001",
  },
  header: {
    balance_cents: 7000,
    open_invoice_count: 1,
    available_credit_cents: 0,
    last_payment: null,
    autopay: {
      state: "off",
      active_count: 0,
      total_count: 1,
      card_last4: null,
      card_label: null,
      next_charge_on: null,
      next_charge_invoice_id: null,
      last_failure: null,
    },
    registration: { state: "registered", card_on_file: false, last_invited_at: null },
    enrollment_counts: { active: 1, paused: 0, cancelled: 0 },
  },
  students: [
    {
      student_id: "stu-a",
      name: "Kid Alpha",
      status: "active",
      enrollments: [],
    },
  ],
  invoices: [],
  timeline: [
    {
      at: "2026-09-04T20:00:00Z",
      kind: "admin",
      code: "enrollment_started",
      summary: "Kid Alpha joined Sat Beginners",
      invoice_id: null,
      invoice_ids: [],
      enrollment_id: null,
      student_name: "Kid Alpha",
      actor_id: null,
      reason: null,
      amount_cents: null,
      muted: false,
    },
  ],
  actions: [],
  warnings: [],
};

function studentDetail(status: "present" | "absent", previous: string | null) {
  return {
    student_id: "stu-a",
    full_name: "Kid Alpha",
    recent_attendance: [
      {
        session_id: "sess-sat",
        date: "2026-09-12",
        status,
        marked_at: "2026-09-12T15:00:00Z",
        occurrence_id: "occ-12",
        previous_status: previous,
        corrected_at: previous ? "2026-09-23T15:00:00Z" : null,
      },
      {
        session_id: "sess-sat",
        date: "2026-09-05",
        status: "present",
        marked_at: "2026-09-05T15:00:00Z",
        occurrence_id: "occ-05",
        previous_status: null,
        corrected_at: null,
      },
    ],
    enrolled_sessions: [],
    payment_history: [],
    outstanding_balance_cents: 0,
  };
}

async function setup(page: Page) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, { ...ADMIN_USER_A, roles: ["admin"] });
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/billing/settings/invoice-schedule", (route) =>
    fulfillJson(route, { billing_day: 1, invoice_due_days: 7 }),
  );
  await page.route("**/api/v2/admin/families/parent-1/record", (route) =>
    fulfillJson(route, RECORD),
  );
  await page.route("**/api/v2/admin/families/parent-1/billing", (route) =>
    fulfillJson(route, BILLING),
  );
  // Details tab (Phase 4b): no other contacts and empty family details.
  await page.route("**/api/v2/admin/families/*/contacts", (route) =>
    fulfillJson(route, { family_id: "parent-1", contacts: [] }),
  );
  await page.route("**/api/v2/admin/families/*/details", (route) =>
    fulfillJson(route, {
      family_id: "parent-1",
      address: null,
      preferred_channel: null,
      heard_about_us: null,
      tags: [],
      updated_by: null,
      updated_at: null,
    }),
  );
  let detail = studentDetail("present", null);
  await page.route("**/api/v2/admin/students/stu-a", (route) => fulfillJson(route, detail));
  await page.route("**/api/v2/admin/students/stu-a/coach-notes", (route) =>
    fulfillJson(route, {
      student_id: "stu-a",
      notes: [
        {
          note_id: "n-1",
          session_id: "sess-sat",
          session_title: "Sat Beginners",
          coach_name: "Coach Testperson",
          body: "Great footwork on the backhand lift today.",
          created_at: "2026-09-12T16:00:00Z",
        },
      ],
    }),
  );
  const patches: { url: string; body: unknown }[] = [];
  await page.route("**/api/v2/admin/session-occurrences/**", (route) => {
    const req = route.request();
    if (req.method() !== "PATCH") return route.fallback();
    const body = req.postDataJSON() as { status: "present" | "absent" };
    patches.push({ url: req.url(), body });
    detail = studentDetail(body.status, "present");
    return fulfillJson(route, {
      attendance_id: "att-12",
      occurrence_id: "occ-12",
      session_id: "sess-sat",
      student_id: "stu-a",
      status: body.status,
      previous_status: "present",
      corrected_by: "u-admin",
      corrected_at: "2026-09-23T15:00:00Z",
    });
  });
  return { errors, patches };
}

test.describe("Family record (People CRM §4)", () => {
  test("opened by a parent alias, it swaps to the canonical family and keeps the tab", async ({
    page,
  }) => {
    const { errors } = await setup(page);
    // Student pages link by the child's stored parent id (here a firebase uid).
    await page.route("**/api/v2/admin/families/fb-alias-1/record", (route) =>
      fulfillJson(route, RECORD),
    );
    await page.route("**/api/v2/admin/families/fb-alias-1/billing", (route) =>
      fulfillJson(route, BILLING),
    );
    await page.goto("/admin/families/fb-alias-1?tab=details");
    await expect(page).toHaveURL(/\/admin\/families\/parent-1\?tab=details$/);
    await expect(page.getByTestId("family-details")).toBeVisible();
    await expect(page.getByTestId("family-record-stage")).toBeVisible();
    await expect(page.getByTestId("details-parent-email")).toHaveText("parent.one@example.test");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("a failed record read is a visible error, not empty cards", async ({ page }) => {
    await setup(page);
    await page.route("**/api/v2/admin/families/parent-9/record", (route) =>
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "family not found" }),
      }),
    );
    await page.route("**/api/v2/admin/families/parent-9/billing", (route) =>
      fulfillJson(route, BILLING),
    );
    await page.goto("/admin/families/parent-9");
    await expect(page.getByTestId("family-record-load-error")).toContainText("unknown, not blank");
    await expect(page).toHaveURL(/\/admin\/families\/parent-9$/);
  });

  test("opens on Overview and switches tabs through ?tab=", async ({ page }) => {
    const { errors } = await setup(page);
    await page.goto("/admin/families/parent-1");
    await expect(page.getByTestId("admin-family-record")).toBeVisible();
    await expect(page.getByTestId("family-record-name")).toHaveText("Test Parent One");
    await expect(page.getByTestId("family-tab-overview")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("family-overview-balance")).toContainText("$70");
    await expect(page.getByTestId("family-overview-child-stu-a")).toContainText("Sat Beginners");

    await page.getByTestId("family-tab-billing").click();
    await expect(page).toHaveURL(/\?tab=billing$/);
    await expect(page.getByTestId("admin-family-billing")).toBeVisible();

    // Arrow keys move along the tablist.
    await page.getByTestId("family-tab-billing").press("ArrowRight");
    await expect(page).toHaveURL(/\?tab=timeline$/);
    await expect(page.getByTestId("family-tab-timeline")).toBeFocused();
    await expect(page.getByTestId("timeline-entry-enrollment_started")).toContainText(
      "Kid Alpha joined",
    );

    await page.getByTestId("family-tab-overview").click();
    await expect(page).toHaveURL(/\/admin\/families\/parent-1\??$/);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("Details shows the primary parent, no other contacts yet, and the details form", async ({
    page,
  }) => {
    const { errors } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=details");
    await expect(page.getByTestId("family-details")).toBeVisible();
    await expect(page.getByTestId("details-parent-email")).toHaveText("parent.one@example.test");
    await expect(page.getByTestId("details-parent-phone")).toHaveText("555-010-0001");
    await expect(page.getByTestId("family-contacts-empty")).toBeVisible();
    await expect(page.getByTestId("family-contact-add-open")).toBeVisible();
    await expect(page.getByTestId("family-details-save")).toBeDisabled();
    await expect(page.getByTestId("family-details-children")).toContainText("Kid Alpha");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("the child drawer shows shared coach notes and returns focus on close", async ({
    page,
  }) => {
    const { errors } = await setup(page);
    await page.goto("/admin/families/parent-1");
    const trigger = page.getByTestId("family-child-open-stu-a");
    await trigger.click();
    const drawer = page.getByTestId("family-child-drawer");
    await expect(drawer).toBeVisible();
    await expect(page.getByTestId("family-child-drawer-name")).toHaveText("Kid Alpha");
    await expect(page.getByTestId("drawer-coach-notes")).toContainText("backhand lift");
    await expect(page.getByTestId("drawer-coach-notes")).toContainText("Coach Testperson");
    await expect(page.getByTestId("family-child-open-full-page")).toHaveAttribute(
      "href",
      "/admin/students/stu-a",
    );
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("correcting a mark needs a confirm step and focus returns to the row", async ({
    page,
  }) => {
    const { patches } = await setup(page);
    await page.goto("/admin/families/parent-1");
    await page.getByTestId("family-child-open-stu-a").click();
    const row = page.getByTestId("drawer-attendance-row-occ-12");
    await expect(row).toContainText("Present");

    await page.getByTestId("drawer-correct-occ-12").click();
    // Choosing a status commits nothing: Review is an explicit step.
    await expect(page.getByTestId("drawer-correction-review")).toBeDisabled();
    await page.getByTestId("drawer-correction-target-absent").check();
    await page.getByTestId("drawer-correction-reason").fill("parent reported a no-show");
    expect(patches).toHaveLength(0);
    await page.getByTestId("drawer-correction-review").click();
    await expect(page.getByTestId("drawer-correction-confirm-copy")).toHaveText(
      "Change Kid Alpha's Sep 12 mark from Present to Absent? The old mark, your name and the reason are kept in the attendance history.",
    );
    expect(patches).toHaveLength(0);
    await page.getByTestId("drawer-correction-confirm-button").click();

    await expect.poll(() => patches.length).toBe(1);
    expect(patches[0].url).toContain("/admin/session-occurrences/occ-12/attendance/stu-a");
    expect(patches[0].body).toEqual({ status: "absent", reason: "parent reported a no-show" });
    await expect(page.getByTestId("drawer-correction-saved")).toHaveText(
      "Sep 12 changed from Present to Absent.",
    );
    await expect(row).toContainText("Absent");
    await expect(row).toContainText("Was Present");
    await expect(page.getByTestId("drawer-correct-occ-12")).toBeFocused();
  });

  test("cancelling a correction returns focus to its Correct button", async ({ page }) => {
    const { patches } = await setup(page);
    await page.goto("/admin/families/parent-1");
    await page.getByTestId("family-child-open-stu-a").click();
    await page.getByTestId("drawer-correct-occ-05").click();
    await page.getByTestId("drawer-correction-form").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByTestId("drawer-correct-occ-05")).toBeFocused();
    expect(patches).toHaveLength(0);
  });
});
