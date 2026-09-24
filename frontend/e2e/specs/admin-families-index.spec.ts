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
import {
  familyIndexRow,
  stubEmptyBillingSetup,
  stubFamilyIndex,
  type FamilyIndexRowFixture,
} from "../fixtures/family-index";

/**
 * People CRM Families view (engineering-spec §3.2) over a mocked family
 * index: search, a preset chip, the class filter, sorting and the money
 * gate. Every name here is fake.
 */

const WITH_CHILD = familyIndexRow({
  family_id: "parent-1",
  parent_name: "Test Parent One",
  phone: "5550100001",
  children: [
    {
      student_id: "stu-a",
      name: "Kid Alpha",
      lifecycle: "active",
      lifecycle_as_of: null,
      classes: [{ session_id: "s-1", title: "Saturday Juniors" }],
      matched: false,
    },
  ],
  money: {
    balance_cents: 7000,
    open_invoice_count: 1,
    overdue_invoice_count: 1,
    overdue_cents: 7000,
    oldest_overdue_due_on: "2026-09-01",
    last_failed_payment_at: null,
  },
});

const NO_ACCOUNT = familyIndexRow({
  family_id: "parent-2",
  parent_name: "Test Parent Two",
  email: null,
  has_account: false,
  stage: "paused",
  card_on_file: null,
  registration: null,
  money: null,
});

async function stubShell(page: Page) {
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "owner" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/sessions*", (route) =>
    fulfillJson(route, {
      sessions: [
        { session_id: "s-1", title: "Saturday Juniors" },
        { session_id: "s-2", title: "Sunday Seniors" },
      ],
    }),
  );
  await stubEmptyBillingSetup(page);
}

/** A tiny server: the stub filters the way the backend does for the params used here. */
function serve(url: URL): FamilyIndexRowFixture[] {
  let rows = [WITH_CHILD, NO_ACCOUNT];
  const search = url.searchParams.get("search")?.toLowerCase();
  if (search) {
    rows = rows
      .map((row) => {
        const kids = row.children.map((c) => ({
          ...c,
          matched: c.name.toLowerCase().startsWith(search),
        }));
        const parent = (row.parent_name ?? "").toLowerCase().includes(search);
        return { ...row, children: kids, matched_parent: parent };
      })
      .filter((row) => row.matched_parent || row.children.some((c) => c.matched));
  }
  if (url.searchParams.get("card_on_file") === "false") {
    rows = rows.filter((row) => row.card_on_file === false);
  }
  const classId = url.searchParams.get("class_id");
  if (classId) {
    rows = rows.filter((row) =>
      row.children.some((c) => c.classes.some((cls) => cls.session_id === classId)),
    );
  }
  return rows;
}

async function setup(
  page: Page,
  opts: { moneyVisible?: boolean; moneyView?: "amounts" | "flag" | "none" } = {},
) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubShell(page);
  const lists: URL[] = [];
  await stubFamilyIndex(page, {
    families: serve,
    moneyVisible: opts.moneyVisible ?? true,
    moneyView: opts.moneyView,
    tiles: { active: 1, leaving: 1, left: 0 },
    presetCounts: { overdue: 1, no_card: 0 },
    onList: (req) => lists.push(new URL(req.url())),
  });
  await page.goto("/admin/families");
  await expect(page.getByTestId("admin-families")).toBeVisible();
  await expect(page.getByTestId("admin-families-row-parent-1")).toBeVisible();
  return { errors, lists };
}

test.describe("admin Families view (People CRM §3.2)", () => {
  test("renders the scope tiles and the family rows", async ({ page }) => {
    const { errors } = await setup(page);
    await expect(page.getByTestId("admin-families-tile-active")).toHaveText("1");
    await expect(page.getByTestId("admin-families-tile-leaving")).toHaveText("1");
    await expect(page.getByTestId("admin-families-tile-total")).toHaveText("2");
    await expect(page.getByTestId("family-link-parent-1")).toHaveAttribute(
      "href",
      "/admin/families/parent-1",
    );
    await expect(page.getByTestId("admin-families-row-parent-1")).toContainText("$70.00");
    // Lane A verify #4: the Overdue and No card chips carry their counts.
    await expect(page.getByTestId("admin-families-preset-overdue-count")).toHaveText("1");
    await expect(page.getByTestId("admin-families-preset-no_card-count")).toHaveText("0");
    await expect(page.getByTestId("admin-families-count")).toHaveText("2 families");
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("a family with no account never links to the Billing page", async ({ page }) => {
    await setup(page);
    const row = page.getByTestId("admin-families-row-parent-2");
    await expect(row).toContainText("Test Parent Two");
    await expect(row).toContainText("No account");
    await expect(page.getByTestId("family-link-parent-2")).toHaveCount(0);
    await expect(row.locator('a[href^="/admin/families/"]')).toHaveCount(0);
  });

  test("search is debounced, kept in the URL, and a child match is the result row", async ({
    page,
  }) => {
    const { lists } = await setup(page);
    await page.locator("#admin-families-search").fill("kid");
    await expect(page.getByTestId("admin-families-child-row-stu-a")).toBeVisible();
    await expect(page.getByTestId("admin-families-child-link-stu-a")).toHaveAttribute(
      "href",
      "/admin/students/stu-a",
    );
    await expect(page.getByTestId("admin-families-row-parent-2")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-count")).toHaveText(
      "1 family matches this search",
    );
    await expect(page).toHaveURL(/[?&]q=kid(&|$)/);
    // One request for the settled query, not one per keystroke.
    const searched = lists.filter((u) => u.searchParams.has("search"));
    expect(searched.map((u) => u.searchParams.get("search"))).toEqual(["kid"]);
  });

  test("a preset chip is a toggle that filters on the server", async ({ page }) => {
    const { lists } = await setup(page);
    const chip = page.getByTestId("admin-families-preset-no_card");
    await expect(chip).toHaveAttribute("aria-pressed", "false");
    await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/card_on_file=false/);
    await expect(page.getByTestId("admin-families-row-parent-1")).toHaveCount(0);
    expect(lists.some((u) => u.searchParams.get("card_on_file") === "false")).toBe(true);
    await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("admin-families-row-parent-1")).toBeVisible();
  });

  test("the class filter narrows the list to one class", async ({ page }) => {
    const { lists } = await setup(page);
    await page.getByTestId("admin-families-class").selectOption("s-1");
    await expect(page).toHaveURL(/class_id=s-1/);
    await expect(page.getByTestId("admin-families-row-parent-2")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-row-parent-1")).toBeVisible();
    expect(lists.some((u) => u.searchParams.get("class_id") === "s-1")).toBe(true);
  });

  test("money stays hidden when the server says so", async ({ page }) => {
    await setup(page, { moneyVisible: false });
    await expect(page.getByTestId("admin-families-preset-overdue")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-preset-no_card")).toBeVisible();
    await expect(page.getByTestId("admin-families-preset-no_card-count")).toHaveText("0");
    await expect(page.getByTestId("admin-families-sort-balance")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-row-parent-1")).not.toContainText("$");
  });

  test("column headers sort on the server", async ({ page }) => {
    const viewport = page.viewportSize();
    test.skip(!viewport || viewport.width < 768, "sortable headers are the desktop table");
    const { lists } = await setup(page);
    const header = page.getByTestId("admin-families-sort-balance");
    await header.click();
    await expect(page).toHaveURL(/sort=balance/);
    await expect(page.locator("th", { has: header })).toHaveAttribute("aria-sort", "descending");
    expect(lists.some((u) => u.searchParams.get("sort") === "balance")).toBe(true);
    await header.click();
    await expect(page).toHaveURL(/order=asc/);
    await expect(page.locator("th", { has: header })).toHaveAttribute("aria-sort", "ascending");
  });
});

test.describe("Families money per staff tier (L2b, #553)", () => {
  test("a front-desk payload shows Owes money and never an amount", async ({ page }) => {
    const { errors } = await setup(page, { moneyView: "flag" });
    await expect(page.getByTestId("admin-families-money-parent-1")).toContainText("Owes money");
    await expect(page.getByTestId("admin-families-row-parent-1")).not.toContainText("$");
    await expect(page.getByTestId("admin-families-sort-balance")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-preset-overdue")).toHaveCount(0);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("the owner previews front desk with Viewing as", async ({ page }) => {
    const { errors } = await setup(page);
    await expect(page.getByTestId("admin-families-money-parent-1")).toContainText("$70");
    await page.getByTestId("viewing-as-select").selectOption("front_desk");
    await expect(page.getByTestId("viewing-as-note")).toBeVisible();
    await expect(page.getByTestId("admin-families-money-parent-1")).toContainText("Owes money");
    await expect(page.getByTestId("admin-families-row-parent-1")).not.toContainText("$");
    await expect(page.getByTestId("admin-families-preset-overdue")).toHaveCount(0);
    await page.getByTestId("viewing-as-select").selectOption("billing");
    await expect(page.getByTestId("admin-families-money-parent-1")).toContainText("$70");
    expect(errors, errors.join("\n")).toEqual([]);
  });
});
