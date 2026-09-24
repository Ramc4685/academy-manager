import { afterEach, describe, expect, it, vi } from "vitest";

import * as client from "./client";
import {
  IMPORT_COLUMNS,
  MAX_IMPORT_BYTES,
  checkImportFile,
  commitFamilyImport,
  commitResultLine,
  importErrorMessage,
  importTemplateCsv,
  needsRecheck,
  previewFamilyImport,
  previewSummaryLine,
  rowStatusLabel,
  type ImportCommitResult,
  type ImportRow,
  type ImportSummary,
} from "./admin-family-import";

afterEach(() => vi.restoreAllMocks());

function apiError(code: string, reason?: string, status = 409) {
  return Object.assign(new Error("backend message"), {
    status,
    code,
    details: reason ? { reason } : undefined,
  });
}

const SUMMARY: ImportSummary = {
  rows_total: 4,
  rows_create: 2,
  rows_skip: 1,
  rows_error: 1,
  families_new: 1,
  families_existing: 1,
};

describe("family import client", () => {
  it("posts the file text and name to the preview, never an academy", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await previewFamilyImport({ csv: "parent_name,student_name\r\n", filename: "kids.csv" });
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/imports/families/preview");
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      csv: "parent_name,student_name\r\n",
      filename: "kids.csv",
    });
  });

  it("omits a missing filename and caps a long one", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await previewFamilyImport({ csv: "x" });
    expect(JSON.parse(String((spy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({ csv: "x" });
    await previewFamilyImport({ csv: "x", filename: `${"a".repeat(300)}.csv` });
    const body = JSON.parse(String((spy.mock.calls[1]?.[1] as RequestInit).body));
    expect(body.filename).toHaveLength(200);
  });

  it("commits by batch id only, never deduplicated", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({} as never);
    await commitFamilyImport("imp_1");
    expect(spy.mock.calls[0]?.[0]).toBe("/admin/imports/families/commit");
    const init = spy.mock.calls[0]?.[1] as RequestInit & { dedup?: boolean };
    expect(init.method).toBe("POST");
    expect(init.dedup).toBe(false);
    expect(JSON.parse(String(init.body))).toEqual({ import_batch_id: "imp_1" });
  });
});

describe("the file", () => {
  it("the template is the accepted header only", () => {
    expect(importTemplateCsv()).toBe(`${IMPORT_COLUMNS.join(",")}\r\n`);
    expect(importTemplateCsv().trim().split("\n")).toHaveLength(1);
  });

  it("refuses empty, oversized and non-CSV files before uploading", () => {
    expect(checkImportFile({ name: "a.csv", size: 0 }).ok).toBe(false);
    expect(checkImportFile({ name: "a.csv", size: MAX_IMPORT_BYTES + 1 }).ok).toBe(false);
    expect(checkImportFile({ name: "a.xlsx", size: 10 }).ok).toBe(false);
    expect(checkImportFile({ name: "A.CSV", size: MAX_IMPORT_BYTES })).toEqual({ ok: true });
  });
});

describe("copy", () => {
  it("maps each refusal to a sentence", () => {
    expect(importErrorMessage(apiError("Crm.InvalidImportFile", undefined, 422))).toBe(
      "backend message",
    );
    expect(importErrorMessage(apiError("Crm.ImportNotCommittable", "has_errors"))).toMatch(
      /changed since the preview/,
    );
    expect(importErrorMessage(apiError("Crm.ImportNotCommittable", "expired"))).toMatch(
      /more than a day old/,
    );
    expect(importErrorMessage(apiError("Crm.ImportNotCommittable", "in_progress"))).toMatch(
      /already running/,
    );
    expect(importErrorMessage(apiError("Crm.ImportUnavailable", undefined, 503))).toMatch(
      /Nothing was imported/,
    );
    expect(importErrorMessage(Object.assign(new Error("x"), { status: 413 }))).toMatch(/too large/);
    expect(importErrorMessage(new Error("boom"))).toMatch(/Nothing was imported/);
  });

  it("re-checks only when the plan changed or is gone", () => {
    expect(needsRecheck(apiError("Crm.ImportNotCommittable", "has_errors"))).toBe(true);
    expect(needsRecheck(apiError("Crm.ImportNotCommittable", "expired"))).toBe(true);
    expect(needsRecheck(apiError("Crm.ImportBatchNotFound", undefined, 404))).toBe(true);
    expect(needsRecheck(apiError("Crm.ImportNotCommittable", "in_progress"))).toBe(false);
    expect(needsRecheck(new Error("network"))).toBe(false);
  });

  it("labels each row result", () => {
    const row = { status: "create", family_action: "new" } as ImportRow;
    expect(rowStatusLabel(row)).toBe("New family");
    expect(rowStatusLabel({ ...row, family_action: "existing" })).toBe("Adds to family");
    expect(rowStatusLabel({ ...row, status: "skip" })).toBe("Already here");
    expect(rowStatusLabel({ ...row, status: "error", family_action: null })).toBe("Problem");
  });

  it("summarises a preview and a commit", () => {
    expect(previewSummaryLine(SUMMARY)).toBe(
      "2 children to add · 1 new family · 1 existing family · 1 row already here · 1 row with problems",
    );
    const done = {
      summary: { ...SUMMARY, rows_error: 0 },
      already_committed: false,
      students_inserted: 2,
    } as ImportCommitResult;
    expect(commitResultLine(done)).toBe(
      "Imported 2 children and 1 new family. 1 row was already here and skipped.",
    );
    expect(commitResultLine({ ...done, already_committed: true })).toMatch(/already imported/);
  });
});
