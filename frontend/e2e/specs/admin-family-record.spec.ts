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

/** People CRM Phase 5: the unified timeline, two pages. */
function timelineEntry(over: Record<string, unknown>) {
  return {
    source: "test",
    detail: null,
    student_id: null,
    student_name: null,
    enrollment_id: null,
    invoice_id: null,
    invoice_ids: [],
    actor_id: null,
    actor_name: null,
    reason: null,
    amount_cents: null,
    refunded_cents: null,
    muted: false,
    collapsed_codes: [],
    ...over,
  };
}

const TIMELINE_PAGE_1 = {
  family_id: "parent-1",
  entries: [
    timelineEntry({
      entry_id: "coach_note:n-1",
      at: "2026-09-06T18:00:00Z",
      kind: "coach",
      code: "coach:note",
      summary: "Coach note from Coach Testcoach · Kid Alpha · Sat Beginners",
      detail: "Great footwork today",
      actor_name: "Coach Testcoach",
    }),
    timelineEntry({
      entry_id: "billing:enrollment_started",
      at: "2026-09-04T20:00:00Z",
      kind: "admin",
      code: "enrollment_started",
      summary: "Kid Alpha joined Sat Beginners",
    }),
  ],
  next_cursor: "cursor-2",
  money_visible: true,
  warnings: [],
};

const TIMELINE_PAGE_2 = {
  family_id: "parent-1",
  entries: [
    timelineEntry({
      entry_id: "audit:au-1",
      at: "2026-08-20T15:00:00Z",
      kind: "admin",
      code: "audit:moved_in",
      summary: "Kid Alpha moved from family Testparent Two",
    }),
  ],
  next_cursor: null,
  money_visible: true,
  warnings: ["attendance_unavailable"],
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
  await page.route("**/api/v2/admin/families/parent-1/timeline**", (route) =>
    fulfillJson(
      route,
      new URL(route.request().url()).searchParams.get("before") === "cursor-2"
        ? TIMELINE_PAGE_2
        : TIMELINE_PAGE_1,
    ),
  );
  // Messages tab (Phase 6): one app email, one unconfirmed WhatsApp handoff.
  const messageLogs: unknown[] = [];
  let messageEntries: Array<Record<string, unknown>> = [
    {
      entry_id: "log:log-1",
      at: "2026-09-21T15:00:00Z",
      channel: "whatsapp",
      source: "staff_log",
      status: "not_logged",
      summary: "WhatsApp opened, not confirmed as sent",
      detail: null,
      recipient: null,
      author_user_id: ADMIN_USER_A.user_id,
      failed_reason: null,
      log_id: "log-1",
      can_complete: true,
    },
    {
      entry_id: "campaign:d-1",
      at: "2026-09-20T15:00:00Z",
      channel: "email",
      source: "campaign",
      status: "failed",
      summary: "Email: Term dates",
      detail: null,
      recipient: "parent.one@example.test",
      author_user_id: null,
      failed_reason: "mailbox full",
      log_id: null,
      can_complete: false,
    },
  ];
  await page.route("**/api/v2/admin/users*", (route) =>
    fulfillJson(route, {
      users: [
        {
          user_id: ADMIN_USER_A.user_id,
          email: "admin@example.com",
          display_name: "Test Admin",
          role: "admin",
          roles: ["admin"],
          status: "active",
        },
      ],
    }),
  );
  await page.route("**/api/v2/admin/families/parent-1/messages", (route) =>
    fulfillJson(route, { family_id: "parent-1", entries: messageEntries, warnings: [] }),
  );
  await page.route("**/api/v2/admin/families/parent-1/messages/log**", (route) => {
    const req = route.request();
    const body = req.postDataJSON() as Record<string, unknown>;
    messageLogs.push({ method: req.method(), url: req.url(), body });
    if (req.method() === "PATCH") {
      messageEntries = messageEntries.map((e) =>
        e.log_id === "log-1" ? { ...e, status: "logged", can_complete: false } : e,
      );
      return fulfillJson(route, messageEntries[0]);
    }
    const row = {
      entry_id: "log:log-2",
      at: "2026-09-23T15:00:00Z",
      channel: body.channel,
      source: "staff_log",
      status: body.status,
      summary: "Phone call",
      detail: body.note ?? null,
      recipient: null,
      author_user_id: ADMIN_USER_A.user_id,
      failed_reason: null,
      log_id: "log-2",
      can_complete: false,
    };
    messageEntries = [row, ...messageEntries];
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(row) });
  });
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
  return { errors, patches, messageLogs };
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
    await expect(page).toHaveURL(/\?tab=messages$/);
    await expect(page.getByTestId("family-tab-messages")).toBeFocused();
    await page.getByTestId("family-tab-messages").press("ArrowRight");
    await expect(page).toHaveURL(/\?tab=timeline$/);
    await expect(page.getByTestId("family-tab-timeline")).toBeFocused();
    await expect(page.getByTestId("timeline-entry-enrollment_started")).toContainText(
      "Kid Alpha joined",
    );
    // Phase 5: the unified feed carries coach notes (read-only, with the
    // coach's name) and pages back with "Show older".
    await expect(page.getByTestId("timeline-entry-coach:note")).toContainText(
      "Coach note from Coach Testcoach",
    );
    await expect(page.getByTestId("timeline-entry-coach:note")).toContainText(
      "Great footwork today",
    );
    await page.getByTestId("family-timeline-older").click();
    await expect(page.getByTestId("timeline-entry-audit:moved_in")).toContainText(
      "moved from family Testparent Two",
    );
    await expect(page.getByTestId("family-timeline-older")).toHaveCount(0);
    await expect(page.getByTestId("family-warnings")).toContainText("attendance_unavailable");

    await page.getByTestId("family-tab-overview").click();
    await expect(page).toHaveURL(/\/admin\/families\/parent-1\??$/);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("Messages lists sends with status, hands off to WhatsApp and logs contacts", async ({
    page,
  }) => {
    const { errors, messageLogs } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=messages");
    await expect(page.getByTestId("family-messages")).toBeVisible();
    const failed = page.getByTestId("family-message-campaign");
    await expect(failed).toHaveAttribute("data-status", "failed");
    await expect(failed).toContainText("Email: Term dates");
    await expect(failed).toContainText("Not delivered: mailbox full");

    // Handoffs open the staff member's own app; the app never sends SMS or WhatsApp.
    await expect(page.getByTestId("family-handoff-whatsapp")).toHaveAttribute(
      "href",
      "https://wa.me/5550100001",
    );
    await expect(page.getByTestId("family-handoff-sms")).toHaveAttribute("href", "sms:5550100001");
    await expect(page.getByTestId("family-handoff-email")).toHaveAttribute(
      "href",
      "mailto:parent.one@example.test",
    );
    await expect(page.getByTestId("family-send-from-app")).toBeDisabled();

    // An earlier unconfirmed handoff is completed from the thread.
    const pending = page.getByTestId("family-message-staff_log");
    await expect(pending).toHaveAttribute("data-status", "not_logged");
    await pending.getByTestId("family-message-complete").click();
    await expect(pending).toHaveAttribute("data-status", "logged");
    // The confirm button is gone; focus lands on its row, not <body>.
    await expect(pending).toBeFocused();
    await expect(page.getByTestId("family-messages-status")).toHaveText("Marked as sent.");

    // A call is logged with a short note.
    await page.getByTestId("family-log-call").click();
    await page.getByTestId("family-contact-log-note").fill("Talked about Saturday class");
    await page.getByTestId("family-contact-log-save").click();
    await expect(page.getByTestId("family-contact-log-form")).toHaveCount(0);
    await expect(page.getByText("Talked about Saturday class")).toBeVisible();
    // The form closed under the focused Save button; focus returns to its opener.
    await expect(page.getByTestId("family-log-call")).toBeFocused();
    await expect(page.getByTestId("family-contact-log-status")).toHaveText("Call logged.");

    // Cancelling also returns focus to the button that opened the form.
    await page.getByTestId("family-log-in_person").click();
    await page.getByTestId("family-contact-log-cancel").click();
    await expect(page.getByTestId("family-contact-log-form")).toHaveCount(0);
    await expect(page.getByTestId("family-log-in_person")).toBeFocused();

    expect(messageLogs).toEqual([
      expect.objectContaining({ method: "PATCH", body: { status: "logged", note: null } }),
      expect.objectContaining({
        method: "POST",
        body: { channel: "call", status: "logged", note: "Talked about Saturday class" },
      }),
    ]);
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

test.describe("Family money per staff tier (L2b, #553)", () => {
  test("a front-desk payload shows Owes money and never an amount", async ({ page }) => {
    const { errors } = await setup(page);
    // What the server sends a front-desk caller: no money block, the flag only.
    await page.route("**/api/v2/admin/families/parent-1/record", (route) =>
      fulfillJson(route, {
        ...RECORD,
        family: { ...RECORD.family, money: null, owes_money: true },
        money_visible: false,
        money_view: "flag",
      }),
    );
    await page.goto("/admin/families/parent-1");
    await expect(page.getByTestId("family-record-owes-money")).toContainText("Owes money");
    await expect(page.getByTestId("family-overview-owes")).toContainText("Owes money");
    await expect(page.getByTestId("family-overview-balance")).toHaveCount(0);
    await expect(page.getByTestId("family-overview")).not.toContainText("$");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("the owner previews front desk with Viewing as", async ({ page }) => {
    const { errors } = await setup(page);
    await stubMe(page, { ...ADMIN_USER_A, roles: ["admin", "owner"] });
    await page.goto("/admin/families/parent-1");
    await expect(page.getByTestId("family-overview-balance")).toContainText("$70");
    await expect(page.getByTestId("family-record-owes-money")).toHaveCount(0);

    await page.getByTestId("viewing-as-select").selectOption("front_desk");
    await expect(page.getByTestId("viewing-as-note")).toBeVisible();
    await expect(page.getByTestId("family-record-owes-money")).toBeVisible();
    await expect(page.getByTestId("family-overview-balance")).toHaveCount(0);
    await expect(page.getByTestId("family-overview")).not.toContainText("$");

    await page.getByTestId("viewing-as-select").selectOption("self");
    await expect(page.getByTestId("family-overview-balance")).toContainText("$70");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("an admin without the owner scope gets no Viewing as control", async ({ page }) => {
    await setup(page);
    await page.goto("/admin/families/parent-1");
    await expect(page.getByTestId("family-overview-balance")).toBeVisible();
    await expect(page.getByTestId("viewing-as")).toHaveCount(0);
  });
});
