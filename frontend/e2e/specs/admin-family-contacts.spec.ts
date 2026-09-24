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
 * People CRM Phase 4b: the family record's Details tab. Add a second contact
 * (both switches start off), turn "Gets notices" on, edit the family details
 * and meet the unsaved-changes guard. Every API is mocked with a small
 * in-memory store; names and addresses are fake.
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

interface StoredContact {
  contact_id: string;
  parent_id: string;
  name: string;
  relationship: string;
  email: string | null;
  phone: string | null;
  gets_notices: boolean;
  gets_invoices: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

async function setup(page: Page) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
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

  const contacts: StoredContact[] = [];
  const sent: { method: string; url: string; body: unknown }[] = [];
  let details = {
    family_id: "parent-1",
    address: null as string | null,
    preferred_channel: null as string | null,
    heard_about_us: null as string | null,
    tags: [] as string[],
    updated_by: null as string | null,
    updated_at: null as string | null,
  };
  let seq = 0;

  await page.route("**/api/v2/admin/families/parent-1/contacts", (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as Omit<StoredContact, "contact_id">;
      sent.push({ method: "POST", url: req.url(), body });
      seq += 1;
      const row: StoredContact = {
        contact_id: `c-${seq}`,
        parent_id: "parent-1",
        name: body.name,
        relationship: body.relationship,
        email: body.email ? body.email.toLowerCase() : null,
        phone: body.phone,
        gets_notices: Boolean(body.gets_notices),
        gets_invoices: Boolean(body.gets_invoices),
        created_by: ADMIN_USER_A.user_id,
        created_at: "2026-09-23T15:00:00Z",
        updated_at: "2026-09-23T15:00:00Z",
      };
      contacts.push(row);
      return fulfillJson(route, row, 201);
    }
    return fulfillJson(route, { family_id: "parent-1", contacts });
  });

  await page.route("**/api/v2/admin/families/parent-1/contacts/*", (route) => {
    const req = route.request();
    const id = new URL(req.url()).pathname.split("/").pop();
    const row = contacts.find((c) => c.contact_id === id);
    if (!row) return fulfillJson(route, { detail: "not found" }, 404);
    if (req.method() === "PATCH") {
      const patch = req.postDataJSON() as Partial<StoredContact>;
      sent.push({ method: "PATCH", url: req.url(), body: patch });
      Object.assign(row, patch, { updated_at: "2026-09-23T16:00:00Z" });
      return fulfillJson(route, row);
    }
    return route.fallback();
  });

  await page.route("**/api/v2/admin/families/parent-1/details", (route) => {
    const req = route.request();
    if (req.method() === "PATCH") {
      const patch = req.postDataJSON() as Partial<typeof details>;
      sent.push({ method: "PATCH", url: req.url(), body: patch });
      details = {
        ...details,
        ...patch,
        updated_by: ADMIN_USER_A.user_id,
        updated_at: "2026-09-23T16:00:00Z",
      };
    }
    return fulfillJson(route, details);
  });

  // People CRM Phase 4c: the Add contact form asks for possible duplicates
  // when the email or phone field is left.
  const checks: Array<Record<string, unknown>> = [];
  await page.route("**/api/v2/admin/people/duplicate-check", (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    checks.push(body);
    const matches =
      body.email === "existing.adult@example.test"
        ? [
            {
              kind: "family",
              display_name: "Existing Testfamily",
              email_masked: "ex***@example.test",
              phone_masked: null,
              link: "/admin/families/parent-9",
              matched_on: ["email"],
            },
          ]
        : [];
    return fulfillJson(route, { matches });
  });

  return { errors, sent, contacts, checks };
}

test.describe("Family contacts and details (People CRM Phase 4b)", () => {
  test("add a second contact, then turn Gets notices on", async ({ page }) => {
    const { errors, sent, contacts } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=details");
    await expect(page.getByTestId("family-contacts-empty")).toBeVisible();

    await page.getByTestId("family-contact-add-open").click();
    const form = page.getByTestId("family-contact-form");
    // Both switches start off, and each is a labelled switch with a description.
    const notices = form.getByRole("switch", { name: "Gets notices" });
    const invoices = form.getByRole("switch", { name: "Gets invoices (opted in)" });
    await expect(notices).not.toBeChecked();
    await expect(invoices).not.toBeChecked();
    await expect(invoices).toHaveAccessibleDescription(
      /Invoice emails to this family also go to this email/,
    );

    // A switch that sends email needs an email: the error sits by the field.
    await form.getByTestId("family-contact-name-input").fill("Second Testparent");
    await form.getByTestId("family-contact-phone").fill("555-010-0002");
    await notices.check();
    await form.getByTestId("family-contact-save").click();
    await expect(form.getByRole("alert")).toContainText("Add an email before turning on");
    expect(sent).toHaveLength(0);

    await notices.uncheck();
    await form.getByTestId("family-contact-email").fill("Second.Parent@example.test");
    await form.getByTestId("family-contact-relationship").selectOption("guardian");
    await form.getByTestId("family-contact-save").click();

    const row = page.getByTestId("family-contact-c-1");
    await expect(row).toContainText("Second Testparent");
    await expect(row).toContainText("(Guardian)");
    await expect(row).toContainText("second.parent@example.test");
    expect(sent[0]).toMatchObject({
      method: "POST",
      body: {
        name: "Second Testparent",
        relationship: "guardian",
        email: "Second.Parent@example.test",
        phone: "555-010-0002",
        gets_notices: false,
        gets_invoices: false,
      },
    });

    const rowNotices = row.getByRole("switch", { name: "Gets notices" });
    await expect(rowNotices).not.toBeChecked();
    await rowNotices.check();
    await expect(rowNotices).toBeChecked();
    await expect(row.getByRole("switch", { name: "Gets invoices (opted in)" })).not.toBeChecked();
    expect(sent[1]).toMatchObject({ method: "PATCH", body: { gets_notices: true } });
    expect(sent[1].url).toMatch(/\/admin\/families\/parent-1\/contacts\/c-1$/);
    expect(contacts[0].gets_notices).toBe(true);
    expect(contacts[0].gets_invoices).toBe(false);
    expect(sent.every((s) => !JSON.stringify(s.body).includes("academy_id"))).toBe(true);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("a possible duplicate is warned about and the contact still saves", async ({ page }) => {
    const { errors, sent, checks } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=details");
    await page.getByTestId("family-contact-add-open").click();
    const form = page.getByTestId("family-contact-form");
    await expect(form.getByTestId("family-contact-duplicate-region")).toHaveAttribute(
      "aria-live",
      "polite",
    );

    await form.getByTestId("family-contact-name-input").fill("Another Testadult");
    await form.getByTestId("family-contact-email").fill("Existing.Adult@example.test");
    await form.getByTestId("family-contact-phone").focus();
    const notice = form.getByTestId("family-contact-duplicate");
    await expect(notice).toContainText("Possible match: Existing Testfamily");
    await expect(form.getByTestId("family-contact-duplicate-open")).toHaveAttribute(
      "href",
      "/admin/families/parent-9",
    );
    expect(checks[0]).toEqual({
      email: "existing.adult@example.test",
      phone: null,
      name: "Another Testadult",
    });

    await form.getByTestId("family-contact-save").click();
    await expect(page.getByTestId("family-contact-c-1")).toContainText("Another Testadult");
    expect(sent[0]).toMatchObject({ method: "POST", body: { name: "Another Testadult" } });
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("family details save only what changed and guard unsaved edits", async ({ page }) => {
    const { errors, sent } = await setup(page);
    await page.goto("/admin/families/parent-1?tab=details");
    const save = page.getByTestId("family-details-save");
    await expect(save).toBeDisabled();

    await page.getByLabel("Home address").fill("1 Test Street");
    await page.getByLabel("Preferred channel").selectOption("whatsapp");
    await expect(page.getByTestId("family-details-dirty")).toBeVisible();

    // Leaving with unsaved edits asks first; staying keeps the draft.
    await page.getByRole("link", { name: "Families" }).first().click();
    await expect(page.getByTestId("unsaved-changes-warning")).toBeVisible();
    await page.getByRole("button", { name: "Stay on this page" }).click();
    await expect(page).toHaveURL(/\/admin\/families\/parent-1\?tab=details$/);
    await expect(page.getByLabel("Home address")).toHaveValue("1 Test Street");

    await save.click();
    await expect(save).toBeDisabled();
    await expect(page.getByTestId("family-details-dirty")).toHaveCount(0);
    expect(sent[0]).toEqual({
      method: "PATCH",
      url: expect.stringMatching(/\/admin\/families\/parent-1\/details$/),
      body: { address: "1 Test Street", preferred_channel: "whatsapp" },
    });
    expect(errors, errors.join("\n")).toEqual([]);
  });
});
