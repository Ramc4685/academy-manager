/**
 * Roadmap L8b: the CSV family import on the Families page. Mirrors
 * backend/v2/interfaces/admin/family_import_routes.py (L8a):
 *
 * - `POST /admin/imports/families/preview` `{filename?, csv}` -> the stored
 *   batch: a dry run, nothing is written.
 * - `POST /admin/imports/families/commit` `{import_batch_id}` -> the
 *   committed batch plus `already_committed` and `students_inserted`.
 *
 * No request carries an academy: the backend uses the caller's tenant. Every
 * decision (grouping, duplicates, what is created or skipped) is the
 * backend's; this module only reads the file and shapes copy.
 */
import { apiFetch, type ApiError } from "./client";

/** The backend's caps (contexts/crm/domain/family_import.py). */
export const MAX_IMPORT_BYTES = 1_000_000;
export const MAX_IMPORT_ROWS = 1_000;

/** The columns the backend accepts, in template order. */
export const IMPORT_COLUMNS = [
  "parent_name",
  "parent_email",
  "parent_phone",
  "student_name",
  "student_date_of_birth",
] as const;

export type ImportRowStatus = "create" | "skip" | "error";

export interface ImportRowIssue {
  field: string;
  message: string;
}

export interface ImportRow {
  line: number;
  status: ImportRowStatus;
  family_action: "new" | "existing" | null;
  family_id: string | null;
  /** Opens an existing family; null for a new one. */
  family_link: string | null;
  family_name: string | null;
  parent_name: string;
  parent_email: string | null;
  parent_phone: string | null;
  student_name: string;
  student_date_of_birth: string | null;
  errors: ImportRowIssue[];
  warnings: string[];
}

export interface ImportSummary {
  rows_total: number;
  rows_create: number;
  rows_skip: number;
  rows_error: number;
  families_new: number;
  families_existing: number;
}

export interface ImportBatch {
  import_batch_id: string;
  status: "previewed" | "committing" | "committed";
  filename: string | null;
  created_at: string;
  committed_at: string | null;
  can_commit: boolean;
  summary: ImportSummary;
  rows: ImportRow[];
}

export interface ImportCommitResult extends ImportBatch {
  already_committed: boolean;
  students_inserted: number;
}

export async function previewFamilyImport(input: {
  csv: string;
  filename?: string | null;
}): Promise<ImportBatch> {
  const body: { csv: string; filename?: string } = { csv: input.csv };
  if (input.filename) body.filename = input.filename.slice(0, 200);
  return apiFetch<ImportBatch>("/admin/imports/families/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function commitFamilyImport(importBatchId: string): Promise<ImportCommitResult> {
  return apiFetch<ImportCommitResult>("/admin/imports/families/commit", {
    method: "POST",
    body: JSON.stringify({ import_batch_id: importBatchId }),
    dedup: false,
  });
}

/** The template: the header row only, so an untouched download imports nothing. */
export function importTemplateCsv(): string {
  return `${IMPORT_COLUMNS.join(",")}\r\n`;
}

export type FileCheck = { ok: true } | { ok: false; message: string };

/** Refuse what the backend would refuse whole, before uploading it. */
export function checkImportFile(file: { name: string; size: number }): FileCheck {
  if (file.size === 0) return { ok: false, message: "This file is empty." };
  if (file.size > MAX_IMPORT_BYTES) {
    return {
      ok: false,
      message: `This file is larger than 1 MB. Split it into smaller files of at most ${MAX_IMPORT_ROWS.toLocaleString("en-US")} rows.`,
    };
  }
  if (!/\.csv$/i.test(file.name)) {
    return { ok: false, message: "Choose a .csv file (in a spreadsheet: File, Download, CSV)." };
  }
  return { ok: true };
}

/** One sentence for the preview/commit failure, from the backend's code. */
export function importErrorMessage(error: unknown): string {
  const err = error as Partial<ApiError> | null;
  const reason = typeof err?.details?.reason === "string" ? err.details.reason : null;
  switch (err?.code) {
    case "Crm.InvalidImportFile":
      return err.message || "This file cannot be imported. Check its columns and try again.";
    case "Crm.ImportNotCommittable":
      if (reason === "has_errors") {
        return "Something changed since the preview and some rows now have problems. Check the file again.";
      }
      if (reason === "expired") {
        return "This preview is more than a day old. Check the file again before importing.";
      }
      if (reason === "in_progress") {
        return "This import is already running. Wait a minute, then check the Families list.";
      }
      return err.message || "This import cannot be run now.";
    case "Crm.ImportBatchNotFound":
      return "This preview was not found. Check the file again.";
    case "Crm.ImportUnavailable":
      return "The family list could not be read, so duplicates cannot be checked. Nothing was imported. Try again shortly.";
    default:
      break;
  }
  if (err?.status === 413) return "This file is too large to upload. Split it into smaller files.";
  if (err?.status === 429) return "Too many imports in a minute. Wait a moment and try again.";
  return "The import could not be checked just now. Nothing was imported. Try again.";
}

/** True when the commit refused because the plan changed: re-check the same file. */
export function needsRecheck(error: unknown): boolean {
  const err = error as Partial<ApiError> | null;
  if (err?.code === "Crm.ImportBatchNotFound") return true;
  if (err?.code !== "Crm.ImportNotCommittable") return false;
  const reason = err.details?.reason;
  return reason === "has_errors" || reason === "expired";
}

export function rowStatusLabel(row: ImportRow): string {
  if (row.status === "error") return "Problem";
  if (row.status === "skip") return "Already here";
  return row.family_action === "existing" ? "Adds to family" : "New family";
}

function plural(count: number, one: string, many: string): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? one : many}`;
}

/** The preview's one-line outcome. */
export function previewSummaryLine(summary: ImportSummary): string {
  const parts = [
    `${plural(summary.rows_create, "child", "children")} to add`,
    `${plural(summary.families_new, "new family", "new families")}`,
    `${plural(summary.families_existing, "existing family", "existing families")}`,
  ];
  if (summary.rows_skip > 0) parts.push(`${plural(summary.rows_skip, "row", "rows")} already here`);
  if (summary.rows_error > 0) {
    parts.push(`${plural(summary.rows_error, "row", "rows")} with problems`);
  }
  return parts.join(" · ");
}

/** The commit's result sentence. */
export function commitResultLine(result: ImportCommitResult): string {
  if (result.already_committed) {
    return "This file was already imported. Nothing new was added.";
  }
  const added = plural(result.students_inserted, "child", "children");
  const families = result.summary.families_new;
  const newFamilies =
    families > 0 ? ` and ${plural(families, "new family", "new families")}` : "";
  const skipped =
    result.summary.rows_skip > 0
      ? ` ${plural(result.summary.rows_skip, "row was", "rows were")} already here and skipped.`
      : "";
  return `Imported ${added}${newFamilies}.${skipped}`;
}
