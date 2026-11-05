/**
 * Phase 2 slice B2: rewrite a spreadsheet export into the five-column family
 * import shape, in the browser, from a column mapping the admin confirmed.
 *
 * Pure. The AI proposes the mapping (`lib/api/admin-ai-import.ts`); nothing it
 * says is written anywhere. The rewritten text goes through the EXISTING
 * preview and commit, which stay the approval gate.
 */
import type { MapColumnsResponse } from "@/lib/api/admin-ai-import";
import { IMPORT_COLUMNS } from "@/lib/api/admin-family-import";

export type ImportColumn = (typeof IMPORT_COLUMNS)[number];

export interface ColumnMapping {
  target: ImportColumn;
  /** One header, or two joined with a space in this order. */
  source_headers: string[];
}

/** Small RFC 4180 reader: quoted cells may hold commas, doubled quotes and newlines. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

function quoteCell(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/** The file's header names (trimmed; a blank header becomes "(column N)"). */
export function readHeaders(csvText: string): string[] {
  const first = parseCsv(csvText)[0] ?? [];
  return first.map((h, i) => h.trim() || `(column ${i + 1})`);
}

export type HeaderCheck =
  | { ok: true }
  | { ok: false; unknown: string[]; missing: string[]; message: string };

/** What the backend's strict header check would say, before uploading. */
export function checkImportHeader(csvText: string): HeaderCheck {
  const names = readHeaders(csvText).map((h) => h.toLowerCase());
  const known = new Set<string>(IMPORT_COLUMNS);
  const unknown = names.filter((n) => !known.has(n));
  const missing = ["parent_name", "student_name"].filter((n) => !names.includes(n));
  if (unknown.length === 0 && missing.length === 0) return { ok: true };
  const parts: string[] = [];
  if (unknown.length > 0) parts.push(`columns this import does not know: ${unknown.join(", ")}`);
  if (missing.length > 0) parts.push(`missing: ${missing.join(", ")}`);
  return { ok: false, unknown, missing, message: `The header has ${parts.join("; ")}.` };
}

/**
 * The CSV rewritten to the mapped import columns, in IMPORT_COLUMNS order.
 * Two source headers join with a single space; blank rows are dropped; a
 * header missing from the file yields an empty cell.
 */
export function applyColumnMapping(csvText: string, mapping: ColumnMapping[]): string {
  const rows = parseCsv(csvText);
  const headers = (rows[0] ?? []).map((h, i) => h.trim() || `(column ${i + 1})`);
  const index = new Map(headers.map((h, i) => [h, i] as const));
  const byTarget = new Map(mapping.map((m) => [m.target, m.source_headers] as const));
  const targets = IMPORT_COLUMNS.filter((c) => byTarget.has(c));
  const out = [targets.map(quoteCell).join(",")];
  for (const row of rows.slice(1)) {
    if (!row.some((c) => c.trim() !== "")) continue;
    const cells = targets.map((t) =>
      (byTarget.get(t) ?? [])
        .map((h) => {
          const at = index.get(h);
          return at === undefined ? "" : (row[at] ?? "").trim();
        })
        .filter((v) => v !== "")
        .join(" ")
    );
    out.push(cells.map(quoteCell).join(","));
  }
  return `${out.join("\r\n")}\r\n`;
}

export type TargetChoice = ImportColumn | "ignore";

/** The draft's choice per header: the target whose sources include it, else ignore. */
export function choicesFromDraft(
  headers: string[],
  draft: Pick<MapColumnsResponse, "mappings">
): Record<string, TargetChoice> {
  const choices: Record<string, TargetChoice> = {};
  for (const header of headers) {
    const hit = draft.mappings.find((m) => m.source_headers.includes(header));
    choices[header] = hit ? hit.target : "ignore";
  }
  return choices;
}

/** Back to a mapping: each target's sources in file order (two join with a space). */
export function mappingFromChoices(
  headers: string[],
  choices: Record<string, TargetChoice>
): ColumnMapping[] {
  return IMPORT_COLUMNS.flatMap((target) => {
    const sources = headers.filter((h) => choices[h] === target);
    return sources.length > 0 ? [{ target, source_headers: sources }] : [];
  });
}
