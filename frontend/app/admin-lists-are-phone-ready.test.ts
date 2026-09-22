import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Issue #847: admins work from a phone about half the time, and every admin
 * list was a desktop `<table>` inside `overflow-x-auto`. At 400px the status,
 * the amount and the row actions were all off-screen behind a sideways scroll,
 * and the tap targets that did fit were 16-32px.
 *
 * The fix is ONE shared two-line phone row (`components/ds/phone-row.tsx`)
 * mounted below `md:` in place of the table — not a second table, and not a
 * CSS-hidden twin (see `lib/use-is-phone.ts` for why the choice is made in JS).
 *
 * These lists render behind auth with a live query client, so — matching
 * `people-are-linked.test.ts` and `sticky-action-columns.test.ts` — this
 * guards the source text rather than mounting the pages. The behaviour at a
 * real 400px viewport is covered by the mobile Playwright projects, which
 * already name these rows by `data-testid`.
 */

const APP = path.resolve(__dirname);
const FRONTEND = path.resolve(__dirname, "..");

function appSource(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

function source(rel: string): string {
  return readFileSync(path.join(FRONTEND, rel), "utf8");
}

const CONVERTED: { name: string; src: () => string }[] = [
  { name: "Students", src: () => appSource("(admin)/admin/students/page.tsx") },
  { name: "Families", src: () => appSource("(admin)/admin/families/page.tsx") },
  { name: "Users", src: () => source("components/admin/AdminUsersDirectory.tsx") },
  { name: "Sessions", src: () => appSource("(admin)/admin/sessions/page.tsx") },
];

/**
 * Issue #857 finishes the rollout #856 started. The approval queues, the money
 * lists and the two detail pages were still bare `<table>` inside
 * `overflow-x-auto`, so every #847 symptom survived there: at 400px the
 * status, the amount and Approve/Deny sat off-screen behind a sideways
 * scroll.
 */
const CONVERTED_857: { name: string; src: () => string }[] = [
  {
    name: "Registrations queue",
    src: () => source("components/admin/admissions/RegistrationsTab.tsx"),
  },
  { name: "Level-ups queue", src: () => source("components/admin/admissions/LevelUpsTab.tsx") },
  { name: "Waitlist queue", src: () => source("components/admin/admissions/WaitlistTab.tsx") },
  {
    name: "Parent request queues",
    src: () => source("components/admin/requests/request-queues.tsx"),
  },
  { name: "All invoices", src: () => appSource("(admin)/admin/payments/AllInvoicesTab.tsx") },
  { name: "Payroll", src: () => appSource("(admin)/admin/payouts/page.tsx") },
  {
    name: "Payslips",
    src: () => appSource("(admin)/admin/payouts/_components/PayslipsPanel.tsx"),
  },
  { name: "Expenses", src: () => appSource("(admin)/admin/expenses/page.tsx") },
  { name: "Billing health webhooks", src: () => appSource("(admin)/admin/billing-health/page.tsx") },
  { name: "Session roster", src: () => appSource("(admin)/admin/sessions/[id]/RosterPanel.tsx") },
  {
    // `ReplacementCoachTable` — the Class dates list the session detail page
    // mounts.
    name: "Session class dates",
    src: () => appSource("(admin)/admin/sessions/[id]/SessionEditing.tsx"),
  },
  {
    name: "Family students",
    src: () => appSource("(admin)/admin/families/[parentId]/StudentsPanel.tsx"),
  },
  {
    name: "Family invoices",
    src: () => appSource("(admin)/admin/families/[parentId]/InvoicesPanel.tsx"),
  },
];

/**
 * #857, the lesson #856 left behind: `admin-users-row-actions-<id>` starts
 * with the SAME string as the row's own `admin-users-row-<id>`. Any prefix
 * match — a CSS `[data-testid^="admin-users-row-"]`, a `startsWith` helper,
 * the string-prefix assertions in this very file — silently picks the actions
 * trigger up as if it were a row. The safe shape is `<list>-actions-<id>`,
 * which shares no prefix with `<list>-row-<id>`.
 */
describe("a row-actions testid never shares a prefix with its row testid (#857)", () => {
  const FILES: { name: string; src: () => string }[] = [
    { name: "Families", src: () => appSource("(admin)/admin/families/page.tsx") },
    { name: "Users", src: () => source("components/admin/AdminUsersDirectory.tsx") },
    ...CONVERTED_857,
  ];

  for (const file of FILES) {
    it(`${file.name} has no \`-row-actions-\` testid`, () => {
      expect(file.src()).not.toMatch(/-row-actions-/);
    });
  }

  it("Families uses admin-families-actions-<parentId>", () => {
    expect(appSource("(admin)/admin/families/page.tsx")).toContain(
      "admin-families-actions-${row.parent_id}",
    );
  });

  it("Users uses admin-users-actions-<userId>", () => {
    expect(source("components/admin/AdminUsersDirectory.tsx")).toContain(
      "admin-users-actions-${user.user_id}",
    );
  });
});

describe("#857 lists mount phone rows below md", () => {
  for (const list of CONVERTED_857) {
    it(`${list.name} swaps the table for PhoneListRow on a phone`, () => {
      const src = list.src();
      expect(src).toContain("useIsPhone");
      expect(src).toContain("PhoneListRow");
      // One layout at a time — see `lib/use-is-phone.ts`. A `md:hidden` twin
      // leaves two nodes per row in the DOM and trips strict mode in every
      // mobile spec that names a row.
      expect(src).not.toContain("md:hidden");
    });
  }
});

/**
 * The money lists keep the confirm step #838 gave them. A phone row that
 * mutated money straight from a menu item would be a second, shorter path to
 * a refund — so each layout hands off to the SAME dialog.
 */
describe("#857 money actions keep the #838 confirm dialogs", () => {
  it("All invoices: the phone menu sets the same targets the buttons set", () => {
    const src = appSource("(admin)/admin/payments/AllInvoicesTab.tsx");
    // One dialog of each kind, mounted once for the tab, driven by a target.
    for (const dialog of ["VoidPaymentDialog", "RefundDialog", "MarkPaidDialog"]) {
      expect(src.match(new RegExp(`<${dialog}`, "g"))?.length).toBe(1);
    }
    // The menu is built from the shared action list, not a hand-rolled copy.
    expect(src).toContain("paymentMenuItems");
  });

  it("All invoices: both layouts derive eligibility once", () => {
    const src = appSource("(admin)/admin/payments/dialogs.tsx");
    expect(src).toContain("function paymentActionEligibility");
    // Refund/undo/void eligibility lives in the shared helper only.
    expect(src.match(/payment\.refunded_cents < finalCents\(payment\)/g)?.length).toBe(1);
  });

  it("Level-ups: approve still routes through ConfirmActionDialog", () => {
    const src = source("components/admin/admissions/LevelUpsTab.tsx");
    expect(src).toContain("ConfirmActionDialog");
    // One dialog per row, shared by the table cell and the phone menu item.
    expect(src.match(/<ConfirmActionDialog/g)?.length).toBe(1);
  });
});

describe("the shared phone row (#847)", () => {
  const row = () => source("components/ds/phone-row.tsx");

  it("is exported from the design system, so lists cannot each grow their own", () => {
    const index = source("components/ds/index.ts");
    expect(index).toContain('export { PhoneList, PhoneListRow } from "./phone-row"');
  });

  it("gives the row-actions trigger a 44px target", () => {
    // The issue's acceptance bar: "every action is reachable with a >=44px
    // target". `min-h-touch`/`min-w-touch` are both 44px in tailwind.config.ts.
    expect(row()).toMatch(/min-h-touch min-w-touch/);
  });

  it("keeps the title line itself at least 44px tall", () => {
    expect(row()).toMatch(/flex min-h-touch/);
  });

  it("opens its actions through the shared overflow menu, not a bespoke popup", () => {
    expect(row()).toContain('from "./menu"');
  });

  it("names the trigger with aria-label, not sr-only text", () => {
    // sr-only text IS text content: "Actions for Amit Rao" would give every
    // `getByText("Amit Rao")` a second match inside the same row and break
    // the existing mobile specs on strict mode.
    expect(row()).toContain("triggerLabel={actionsLabel}");
    expect(row()).not.toContain('className="sr-only">{actionsLabel}');
    expect(source("components/ds/menu.tsx")).toContain("aria-label={triggerLabel}");
  });
});

describe("every converted admin list mounts phone rows below md (#847)", () => {
  for (const list of CONVERTED) {
    it(`${list.name} swaps the table for PhoneListRow on a phone`, () => {
      const src = list.src();
      expect(src).toContain("useIsPhone");
      expect(src).toContain("PhoneListRow");
      // One layout at a time: a `md:hidden` twin would leave two nodes per
      // row in the DOM and break every mobile spec that names a row.
      expect(src).not.toContain("md:hidden");
    });
  }
});

describe("phone rows keep the table's row ids, so mobile specs still resolve (#847)", () => {
  it("Students rows and their student/family links", () => {
    const src = appSource("(admin)/admin/students/page.tsx");
    expect(src).toContain("data-testid={`admin-students-row-${student.student_id}`}");
    expect(
      src.match(/admin-students-link-\$\{student\.student_id\}/g)?.length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("Families rows keep family-link-<parentId> on the phone row too", () => {
    const src = appSource("(admin)/admin/families/page.tsx");
    expect(src.match(/family-link-\$\{row\.parent_id\}/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("Users rows keep admin-users-row-<userId>", () => {
    const src = source("components/admin/AdminUsersDirectory.tsx");
    expect(src.match(/admin-users-row-\$\{user\.user_id\}/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("Sessions keeps admin-sessions-table on the wrapper, so it exists at both widths", () => {
    const src = appSource("(admin)/admin/sessions/page.tsx");
    // Scoped lookups like `[data-testid="admin-sessions-table"]
    // [data-testid^="session-row-"]` (saas-tenant-isolation.spec.ts) run under
    // the mobile projects, so the hook may not live on the <table> itself.
    expect(src).not.toMatch(/<table[^>]*data-testid="admin-sessions-table"/);
    expect(src.match(/data-testid="admin-sessions-table"/g)?.length).toBe(2);
    expect(src.match(/data-testid=\{`session-row-\$\{s\.session_id\}`\}/g)?.length).toBe(2);
  });
});

describe("the desktop fixes that ship with the phone rows (#847)", () => {
  it("Students: Lifecycle sits beside the name, not in a trailing column", () => {
    const src = appSource("(admin)/admin/students/page.tsx");
    expect(src).not.toContain(">Lifecycle</th>");
    // Still rendered — in the name cell and in the phone row's second line.
    expect(src.match(/<LifecycleChip/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("Sessions: the list says which day, at every width", () => {
    const src = appSource("(admin)/admin/sessions/page.tsx");
    expect(src).toContain("<Th>Day</Th>");
    expect(src).toContain("function sessionDayLabel");
    // Read in the session's own timezone, or the class moves a day for an
    // admin in another zone.
    expect(src).toContain("resolveAcademyTimeZone(session.timezone)");
  });

  it("All invoices: the actions column is sticky, so it survives 1280", () => {
    const src = appSource("(admin)/admin/payments/AllInvoicesTab.tsx");
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
    expect(src).not.toContain('<Th><span className="sr-only">Actions</span></Th>');
  });

  it("Sessions: Edit/Cancel are sticky too, now that Day made it a ninth column", () => {
    const src = appSource("(admin)/admin/sessions/page.tsx");
    expect(src).toContain("actionHeaderClass");
    expect(src).toContain("actionCellClass");
  });
});

describe("phone filter controls clear 44px (#847)", () => {
  // #897: the three lists used to carry three copies of this className. They
  // now share one `FilterChip`, so the 44px rule is asserted once, where it
  // lives, and each page is checked for using it.
  it("the shared filter chip is 44px on a phone and 32px from md up", () => {
    const src = source("components/ds/list-toolbar.tsx");
    expect(src).toContain("min-h-touch");
    expect(src).toContain("md:h-8 md:min-h-0");
  });

  it("Students lifecycle tabs", () => {
    expect(appSource("(admin)/admin/students/page.tsx")).toContain("<FilterChip");
  });

  it("Families status filters", () => {
    expect(appSource("(admin)/admin/families/page.tsx")).toContain("<FilterChip");
  });

  it("Users role tabs", () => {
    expect(source("components/admin/AdminUsersDirectory.tsx")).toContain("<FilterChip");
  });
});
