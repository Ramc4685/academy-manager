/**
 * Phase 2 slice B2: the roster-import copilot. Mirrors
 * backend/v2/interfaces/admin/ai_import_routes.py.
 *
 * - `POST /admin/imports/families/map-columns` `{filename?, csv}` -> a column
 *   mapping draft plus `sample_mode` (`masked` or `values`) and the prompt
 *   version. Nothing is written but the `ai_calls` audit row.
 * - `GET`/`PUT /admin/ai/import-sharing` (owner only): whether the model may
 *   see real spreadsheet values instead of masked samples.
 * - `GET /admin/ai/status` is slice B1's; here it only decides whether the
 *   "Map columns with AI" button shows at all.
 */
import { apiFetch, type ApiError } from "./client";
import type { ColumnMapping, ImportColumn } from "@/lib/admin/import-column-mapping";

export interface ColumnMappingDraftRow extends ColumnMapping {
  target: ImportColumn;
  confidence: "high" | "medium" | "low";
  note: string;
}

export interface MapColumnsResponse {
  mappings: ColumnMappingDraftRow[];
  unmapped_headers: string[];
  notes: string;
  sample_mode: "masked" | "values";
  prompt_version: string;
}

export async function mapImportColumns(input: {
  csv: string;
  filename?: string | null;
}): Promise<MapColumnsResponse> {
  const body: { csv: string; filename?: string } = { csv: input.csv };
  if (input.filename) body.filename = input.filename.slice(0, 200);
  return apiFetch<MapColumnsResponse>("/admin/imports/families/map-columns", {
    method: "POST",
    body: JSON.stringify(body),
    dedup: false,
  });
}

export interface AiStatus {
  enabled: boolean;
}

/** Slice B1's endpoint; absent (404) or failing means the AI button stays hidden. */
export function getAiStatus(): Promise<AiStatus> {
  return apiFetch<AiStatus>("/admin/ai/status", { method: "GET" });
}

export interface ImportSharingView {
  share_values: boolean;
}

export function getImportSharing(): Promise<ImportSharingView> {
  return apiFetch<ImportSharingView>("/admin/ai/import-sharing", { method: "GET" });
}

export function setImportSharing(shareValues: boolean): Promise<ImportSharingView> {
  return apiFetch<ImportSharingView>("/admin/ai/import-sharing", {
    method: "PUT",
    body: JSON.stringify({ share_values: shareValues }),
  });
}

/** One sentence for a failed mapping request, from the backend's status. */
export function mapColumnsErrorMessage(error: unknown): string {
  const err = error as Partial<ApiError> | null;
  switch (err?.status) {
    case 503:
      return "AI import help is not enabled for this academy yet";
    case 429:
      return "This academy has used its AI drafts for the month";
    case 502:
      return "The mapping could not be read, try again";
    case 413:
      return "This file is too large to upload. Split it into smaller files.";
    case 422:
      return err?.message || "This file could not be read as a CSV.";
    default:
      return "The columns could not be mapped just now. Try again.";
  }
}
