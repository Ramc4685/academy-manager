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
 * People CRM Phase 4a: the family record's Notes & follow-ups tab (add a
 * note, add a follow-up with a due date and an assignee, mark it done) and
 * the dashboard's "My follow-ups" card. Every API is mocked with a small
 * in-memory store; the inbox polls are stubbed. Names are fake.
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

const ME = ADMIN_USER_A.user_id;
const STAFF = {
  users: [
    {
      user_id: ME,
      email: "admin@example.com",
      display_name: "Test Admin",
      role: "admin",
      roles: ["admin", "owner"],
      status: "active",
    },
    {
      user_id: "user-desk-1",
      email: "desk@example.test",
      display_name: "Desk Testperson",
      role: "admin",
      roles: ["admin"],
      status: "active",
    },
  ],
};

interface StoredFollowUp {
  follow_up_id: string;
  parent_id: string;
  family_name: string | null;
  title: string;
  due_on: string;
  assignee_user_id: string;
  status: "open" | "done";
  bucket: "overdue" | "today" | "upcoming" | "done";
  created_by: string;
  created_at: string;
  updated_at: string;
  done_at: string | null;
  done_by: string | null;
}

const TODAY = "2026-09-23";

function bucketOf(row: StoredFollowUp): StoredFollowUp["bucket"] {
  if (row.status === "done") return "done";
  if (row.due_on < TODAY) return "overdue";
  return row.due_on === TODAY ? "today" : "upcoming";
}

async function setup(page: Page) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "admin" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) =>
    fulfillJson(route, { messages: [] }),
  );
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
  await page.route("**/api/v2/admin/users*", (route) => fulfillJson(route, STAFF));

  const notes: Array<Record<string, unknown>> = [];
  const followUps: StoredFollowUp[] = [];
  const posted: { url: string; body: unknown }[] = [];
  let seq = 0;

  await page.route("**/api/v2/admin/families/parent-1/notes", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as { body: string };
      posted.push({ url: req.url(), body });
      seq += 1;
      const note = {
        note_id: `note-${seq}`,
        parent_id: "parent-1",
        body: body.body.trim(),
        author_user_id: ME,
        created_at: "2026-09-23T15:00:00Z",
        updated_at: "2026-09-23T15:00:00Z",
        edited: false,
        can_edit: true,
      };
      notes.unshift(note);
      return fulfillJson(route, note, 201);
    }
    return fulfillJson(route, { family_id: "parent-1", notes });
  });

  await page.route("**/api/v2/admin/families/parent-1/follow-ups", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as {
        title: string;
        due_on: string;
        assignee_user_id: string;
      };
      posted.push({ url: req.url(), body });
      seq += 1;
      const row: StoredFollowUp = {
        follow_up_id: `fu-${seq}`,
        parent_id: "parent-1",
        family_name: "Test Parent One",
        title: body.title,
        due_on: body.due_on,
        assignee_user_id: body.assignee_user_id,
        status: "open",
        bucket: "today",
        created_by: ME,
        created_at: "2026-09-23T15:00:00Z",
        updated_at: "2026-09-23T15:00:00Z",
        done_at: null,
        done_by: null,
      };
      row.bucket = bucketOf(row);
      followUps.unshift(row);
      return fulfillJson(route, row, 201);
    }
    return fulfillJson(route, { family_id: "parent-1", today: TODAY, follow_ups: followUps });
  });

  await page.route("**/api/v2/admin/families/parent-1/follow-ups/*", (route) => {
    const req = route.request();
    if (req.method() !== "PATCH") return route.fallback();
    const id = new URL(req.url()).pathname.split("/").pop();
    const row = followUps.find((f) => f.follow_up_id === id);
    if (!row) return fulfillJson(route, { detail: "not found" }, 404);
    const patch = req.postDataJSON() as { status?: "open" | "done" };
    posted.push({ url: req.url(), body: patch });
    if (patch.status) {
      row.status = patch.status;
      row.done_at = patch.status === "done" ? "2026-09-23T16:00:00Z" : null;
      row.done_by = patch.status === "done" ? ME : null;
      row.bucket = bucketOf(row);
    }
    return fulfillJson(route, row);
  });

  await page.route("**/api/v2/admin/follow-ups*", (route) => {
    const url = new URL(route.request().url());
    const mine = url.searchParams.get("assignee") !== "all";
    const rows = followUps.filter(
      (f) => f.status === "open" && (!mine || f.assignee_user_id === ME),
    );
    return fulfillJson(route, {
      today: TODAY,
      assignee: mine ? "me" : "all",
      bucket: null,
      follow_ups: rows,
    });
  });

  return { errors, posted, followUps };
}

test.describe("Family notes and follow-ups (People CRM Phase 4a)", () => {
  test("add a note, add a follow-up, mark it done", async ({ page }) => {
    const { errors, posted } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=notes");
    await expect(page.getByTestId("family-tab-notes")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("family-notes-empty")).toBeVisible();
    await expect(page.getByTestId("family-follow-ups-empty")).toBeVisible();

    // An empty note is refused in the browser; nothing is sent.
    await page.getByTestId("family-note-add").click();
    await expect(page.getByTestId("family-note-error")).toContainText("Write something");
    expect(posted).toHaveLength(0);

    await page
      .getByTestId("family-note-draft")
      .fill("Prefers a text before class.\nAsk about sibling.");
    await page.getByTestId("family-note-add").click();
    const list = page.getByTestId("family-notes-list");
    await expect(list).toContainText("Prefers a text before class.");
    await expect(list).toContainText("You");
    await expect(page.getByTestId("family-note-draft")).toHaveValue("");
    expect(posted[0].body).toEqual({ body: "Prefers a text before class.\nAsk about sibling." });

    // The follow-up form defaults to today and to the signed-in admin.
    await expect(page.getByTestId("follow-up-due")).toHaveValue(TODAY);
    await expect(page.getByTestId("follow-up-assignee")).toHaveValue(ME);
    await page.getByTestId("follow-up-title").fill("Call back about the trial");
    await page.getByTestId("follow-up-due").fill("2026-09-22");
    await page.getByTestId("follow-up-assignee").selectOption("user-desk-1");
    await page.getByTestId("follow-up-add").click();

    const row = page.getByTestId("family-follow-ups-list").locator("li").first();
    await expect(row).toContainText("Call back about the trial");
    await expect(row).toContainText("Overdue");
    await expect(row).toContainText("Desk Testperson");
    expect(posted[1].body).toEqual({
      title: "Call back about the trial",
      due_on: "2026-09-22",
      assignee_user_id: "user-desk-1",
    });

    await row.getByTestId("follow-up-done").click();
    await expect(row).toHaveAttribute("data-status", "done");
    await expect(row).toContainText("Done");
    await expect(row.getByTestId("follow-up-reopen")).toBeVisible();
    expect(posted[2].body).toEqual({ status: "done" });
    expect(posted.every((p) => !JSON.stringify(p.body).includes("academy_id"))).toBe(true);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("the dashboard lists my overdue and due-today follow-ups", async ({ page }) => {
    const { errors, followUps } = await setup(page);
    await page.route("**/api/v2/admin/dashboard/attention*", (route) =>
      fulfillJson(route, { items: [] }),
    );
    await page.route("**/api/v2/admin/sessions*", (route) => fulfillJson(route, { sessions: [] }));
    const base: Omit<StoredFollowUp, "follow_up_id" | "title" | "due_on" | "assignee_user_id"> = {
      bucket: "today",
      parent_id: "parent-1",
      family_name: "Test Parent One",
      status: "open",
      created_by: ME,
      created_at: "2026-09-20T15:00:00Z",
      updated_at: "2026-09-20T15:00:00Z",
      done_at: null,
      done_by: null,
    };
    const mine = { ...base, assignee_user_id: ME };
    followUps.push(
      { ...mine, follow_up_id: "fu-a", title: "Send the waiver link", due_on: "2026-09-21" },
      { ...mine, follow_up_id: "fu-b", title: "Confirm Saturday spot", due_on: TODAY },
      { ...mine, follow_up_id: "fu-c", title: "Next month check-in", due_on: "2026-10-05" },
    );
    for (const row of followUps) row.bucket = bucketOf(row);
    await page.goto("/admin");
    const card = page.getByTestId("dashboard-my-follow-ups");
    await expect(card).toBeVisible();
    await expect(page.getByTestId("dashboard-my-follow-ups-counts")).toHaveText(
      "1 overdue, 1 due today",
    );
    await expect(card).toContainText("Send the waiver link");
    await expect(card).toContainText("Confirm Saturday spot");
    await expect(card).not.toContainText("Next month check-in");
    await expect(page.getByTestId("dashboard-follow-up-fu-a")).toHaveAttribute(
      "href",
      "/admin/families/parent-1?tab=notes",
    );
    expect(errors.filter((e) => /follow-ups/.test(e)), errors.join("\n")).toEqual([]);
  });
});
