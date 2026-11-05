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

/** One header as the backend names it: trimmed, blank -> "(column N)", cut to 80 characters. */
function headerName(raw: string, i: number): string {
  return (raw.trim() || `(column ${i + 1})`).slice(0, 80);
}

/** The file's header names, normalized like the backend's so the draft's headers match. */
export function readHeaders(csvText: string): string[] {
  return (parseCsv(csvText)[0] ?? []).map(headerName);
}

export type HeaderCheck =
  | { ok: true }
  | { ok: false; unknown: string[]; missing: string[]; duplicate?: string; message: string };

/** The first header that repeats an earlier one, case and spaces aside; mirrors the backend. */
export function duplicateHeader(headers: string[]): string | undefined {
  const seen = new Set<string>();
  for (const h of headers) {
    const key = h.toLowerCase().replace(/\s+/g, "");
    if (seen.has(key)) return h;
    seen.add(key);
  }
  return undefined;
}

/** What the backend's strict header check would say, before uploading. */
export function checkImportHeader(csvText: string): HeaderCheck {
  const headers = readHeaders(csvText);
  const duplicate = duplicateHeader(headers);
  if (duplicate !== undefined) {
    const message = `The file has two columns named ${duplicate}; rename one and try again.`;
    return { ok: false, unknown: [], missing: [], duplicate, message };
  }
  const names = headers.map((h) => h.toLowerCase());
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
  const headers = (rows[0] ?? []).map(headerName);
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

/**
 * The headers in the order sources join: the draft's own order first (so
 * ["First","Last"] stays "Jane Doe" whatever the file order), then the rest in
 * file order. Pass this, not the file headers, to `mappingFromChoices`.
 */
export function sourceOrder(headers: string[], draft: Pick<MapColumnsResponse, "mappings">): string[] {
  const first = draft.mappings.flatMap((m) => m.source_headers).filter((h) => headers.includes(h));
  return [...new Set([...first, ...headers])];
}

/** The order with two headers' positions exchanged. */
export function swapSources(order: string[], a: string, b: string): string[] {
  return order.map((h) => (h === a ? b : h === b ? a : h));
}

/** Back to a mapping: each target's sources in `order` (two join with a space). */
export function mappingFromChoices(
  order: string[],
  choices: Record<string, TargetChoice>
): ColumnMapping[] {
  return IMPORT_COLUMNS.flatMap((target) => {
    const sources = order.filter((h) => choices[h] === target);
    return sources.length > 0 ? [{ target, source_headers: sources }] : [];
  });
}
