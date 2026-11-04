import { test, expect, type Page, type Request } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";
import { stubEmptyBillingSetup, stubFamilyIndex } from "../fixtures/family-index";

/**
 * Roadmap L8b: the CSV import panel on the Families page, over a stubbed
 * preview/commit API (L8a). Every name, email and phone here is fake.
 */

const CSV = [
  "parent_name,parent_email,parent_phone,student_name,student_date_of_birth",
  "Test Parent One,one@example.test,,Kid Alpha,2016-04-01",
  "Test Parent Two,,5550100002,Kid Beta,",
  "Test Parent Three,three@example.test,,Kid Gamma,",
].join("\r\n");

function row(line: number, over: Record<string, unknown>) {
  return {
    line,
    status: "create",
    family_action: "new",
    family_id: `parent_${line}`,
    family_link: null,
    family_name: null,
    parent_name: `Test Parent ${line}`,
    parent_email: null,
    parent_phone: null,
    student_name: `Kid ${line}`,
    student_date_of_birth: null,
    errors: [],
    warnings: [],
    ...over,
  };
}

const CLEAN_ROWS = [
  row(2, { parent_name: "Test Parent One", parent_email: "one@example.test", student_name: "Kid Alpha", student_date_of_birth: "2016-04-01" }),
  row(3, {
    parent_name: "Test Parent Two",
    parent_phone: "5550100002",
    student_name: "Kid Beta",
    family_action: "existing",
    family_id: "parent-2",
    family_link: "/admin/families/parent-2",
    family_name: "Test Parent Two",
  }),
  row(4, { status: "skip", family_action: "existing", family_id: "parent-3", family_link: "/admin/families/parent-3", family_name: "Test Parent Three", parent_name: "Test Parent Three", student_name: "Kid Gamma" }),
];

function batch(rows: ReturnType<typeof row>[], over: Record<string, unknown> = {}) {
  const count = (status: string) => rows.filter((r) => r.status === status).length;
  const errors = count("error");
  return {
    import_batch_id: "imp_test_1",
    status: "previewed",
    filename: "families.csv",
    created_at: "2026-09-24T15:00:00Z",
    committed_at: null,
    can_commit: errors === 0,
    summary: {
      rows_total: rows.length,
      rows_create: count("create"),
      rows_skip: count("skip"),
      rows_error: errors,
      families_new: rows.filter((r) => r.status === "create" && r.family_action === "new").length,
      families_existing: 1,
    },
    rows,
    ...over,
  };
}

async function setup(page: Page) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "owner" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/sessions*", (route) => fulfillJson(route, { sessions: [] }));
  await stubEmptyBillingSetup(page);
  const lists: Request[] = [];
  await stubFamilyIndex(page, { families: [], onList: (req) => lists.push(req) });
  await page.goto("/admin/families");
  await expect(page.getByTestId("admin-families")).toBeVisible();
  await page.getByTestId("admin-families-import-open").click();
  await expect(page.getByTestId("admin-families-import")).toBeVisible();
  return { errors, lists };
}

async function chooseCsv(page: Page, name = "families.csv", text = CSV) {
  await page.getByTestId("admin-families-import-file").setInputFiles({
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(text, "utf-8"),
  });
}

test.describe("admin family CSV import (roadmap L8b)", () => {
  test("check, preview every row, confirm, and see the result", async ({ page }) => {
    const { errors, lists } = await setup(page);
    const previews: unknown[] = [];
    const commits: unknown[] = [];
    await page.route("**/api/v2/admin/imports/families/preview", (route) => {
      previews.push(route.request().postDataJSON());
      return fulfillJson(route, batch(CLEAN_ROWS));
    });
    await page.route("**/api/v2/admin/imports/families/commit", (route) => {
      commits.push(route.request().postDataJSON());
      return fulfillJson(route, {
        ...batch(CLEAN_ROWS, { status: "committed", committed_at: "2026-09-24T15:01:00Z", can_commit: false }),
        already_committed: false,
        students_inserted: 2,
      });
    });

    await chooseCsv(page);
    await page.getByTestId("admin-families-import-preview").click();

    await expect(page.getByTestId("admin-families-import-summary")).toHaveText(
      "2 children to add · 1 new family · 1 existing family · 1 row already here",
    );
    expect(previews).toEqual([{ csv: CSV, filename: "families.csv" }]);
    await expect(page.getByTestId("admin-families-import-row-2")).toContainText("New family");
    await expect(page.getByTestId("admin-families-import-row-3")).toContainText("Adds to family");
    await expect(
      page.getByTestId("admin-families-import-row-3").getByRole("link", { name: "Test Parent Two" }),
    ).toHaveAttribute("href", "/admin/families/parent-2");
    await expect(page.getByTestId("admin-families-import-row-4")).toContainText("Already here");

    const listsBefore = lists.length;
    await page.getByTestId("admin-families-import-commit").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Nobody is emailed");
    expect(commits).toEqual([]);
    await dialog.getByRole("button", { name: "Import", exact: true }).click();

    await expect(page.getByTestId("admin-families-import-result")).toContainText(
      "Imported 2 children and 1 new family. 1 row was already here and skipped.",
    );
    expect(commits).toEqual([{ import_batch_id: "imp_test_1" }]);
    // The Families list refreshes after the import.
    await expect.poll(() => lists.length).toBeGreaterThan(listsBefore);
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("controls that remove themselves hand focus on, never to the page body", async ({
    page,
  }) => {
    const { errors } = await setup(page);
    await page.route("**/api/v2/admin/imports/families/preview", (route) =>
      fulfillJson(route, batch(CLEAN_ROWS)),
    );
    await page.route("**/api/v2/admin/imports/families/commit", (route) =>
      fulfillJson(route, {
        ...batch(CLEAN_ROWS, { status: "committed", committed_at: "2026-09-24T15:01:00Z", can_commit: false }),
        already_committed: false,
        students_inserted: 2,
      }),
    );

    await chooseCsv(page);
    await page.getByTestId("admin-families-import-preview").click();
    await page.getByTestId("admin-families-import-choose-another").click();
    await expect(page.getByTestId("admin-families-import-file")).toBeFocused();

    await chooseCsv(page);
    await page.getByTestId("admin-families-import-preview").click();
    await page.getByTestId("admin-families-import-commit").click();
    await page.getByRole("dialog").getByRole("button", { name: "Import", exact: true }).click();
    await page.getByTestId("admin-families-import-again").click();
    await expect(page.getByTestId("admin-families-import-file")).toBeFocused();

    await page.getByTestId("admin-families-import-close").click();
    await expect(page.getByTestId("admin-families-import-open")).toBeFocused();
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("a row with a problem blocks the import and says why", async ({ page }) => {
    await setup(page);
    const rows = [
      CLEAN_ROWS[0],
      row(3, {
        status: "error",
        family_action: null,
        family_id: null,
        parent_email: "=bad@example.test",
        errors: [{ field: "parent_email", message: "parent_email must not start with = + - @." }],
      }),
    ];
    let commits = 0;
    await page.route("**/api/v2/admin/imports/families/preview", (route) =>
      fulfillJson(route, batch(rows)),
    );
    await page.route("**/api/v2/admin/imports/families/commit", (route) => {
      commits += 1;
      return fulfillJson(route, {});
    });

    await chooseCsv(page);
    await page.getByTestId("admin-families-import-preview").click();
    await expect(page.getByTestId("admin-families-import-summary")).toContainText(
      "1 row with problems",
    );
    // Opens on the problems only; the toggle shows every row again.
    await expect(page.getByTestId("admin-families-import-row-2")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-import-row-3")).toContainText(
      "must not start with",
    );
    await page.getByTestId("admin-families-import-only-problems").uncheck();
    await expect(page.getByTestId("admin-families-import-row-2")).toBeVisible();

    await expect(page.getByTestId("admin-families-import-commit")).toBeDisabled();
    await expect(page.getByTestId("admin-families-import-blocked")).toBeVisible();
    expect(commits).toBe(0);
  });

  test("a whole-file refusal and a changed plan are explained, and the file re-checked", async ({
    page,
  }) => {
    await setup(page);
    let previewCalls = 0;
    await page.route("**/api/v2/admin/imports/families/preview", (route) => {
      previewCalls += 1;
      if (previewCalls === 1) {
        return fulfillJson(
          route,
          {
            error: {
              code: "Crm.InvalidImportFile",
              message: "Unknown column: kid_name.",
              details: {},
            },
          },
          422,
        );
      }
      return fulfillJson(route, batch(CLEAN_ROWS));
    });
    await page.route("**/api/v2/admin/imports/families/commit", (route) =>
      fulfillJson(
        route,
        {
          error: {
            code: "Crm.ImportNotCommittable",
            message: "not committable",
            details: { reason: "has_errors" },
          },
        },
        409,
      ),
    );

    await chooseCsv(page);
    await page.getByTestId("admin-families-import-preview").click();
    await expect(page.getByTestId("admin-families-import-preview-error")).toContainText(
      "Unknown column: kid_name.",
    );

    await page.getByTestId("admin-families-import-preview-error").getByRole("button").click();
    await expect(page.getByTestId("admin-families-import-summary")).toBeVisible();
    await page.getByTestId("admin-families-import-commit").click();
    await page.getByRole("dialog").getByRole("button", { name: "Import", exact: true }).click();

    const notice = page.getByTestId("admin-families-import-commit-error");
    await expect(notice).toContainText("changed since the preview");
    await expect(page.getByTestId("admin-families-import-commit")).toBeDisabled();
    await notice.getByRole("button").click();
    await expect.poll(() => previewCalls).toBe(3);
    await expect(page.getByTestId("admin-families-import-commit-error")).toHaveCount(0);
    await expect(page.getByTestId("admin-families-import-commit")).toBeEnabled();
  });

  test("a file that is not a CSV is refused before any upload", async ({ page }) => {
    await setup(page);
    let previews = 0;
    await page.route("**/api/v2/admin/imports/families/preview", (route) => {
      previews += 1;
      return fulfillJson(route, batch(CLEAN_ROWS));
    });
    await chooseCsv(page, "families.xlsx");
    await expect(page.getByTestId("admin-families-import-file-error")).toContainText(".csv");
    await expect(page.getByTestId("admin-families-import-preview")).toHaveCount(0);
    expect(previews).toBe(0);
  });
});
