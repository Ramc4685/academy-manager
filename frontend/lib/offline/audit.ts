"use client";

import { getAll, put } from "./idb";

/**
 * Local audit log of mutation outcomes. Used by the "Needs review" tray's
 * export and by post-incident forensics.
 *
 * 30-day retention enforced via `pruneOlderThanDays`.
 */

export interface AuditEntry {
  id?: number;
  kind: "synced" | "needs_review" | "dismissed" | "exported";
  mutation_id: string;
  endpoint: string;
  error_code?: string;
  ts: string; // ISO
}

const STORE = "audit" as const;

export async function recordAudit(entry: AuditEntry): Promise<void> {
  await put(STORE, entry);
}

export async function listAudit(): Promise<AuditEntry[]> {
  return (await getAll<AuditEntry>(STORE)).sort((a, b) => a.ts.localeCompare(b.ts));
}

export async function pruneOlderThanDays(days: number): Promise<number> {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  const items = await listAudit();
  let removed = 0;
  for (const e of items) {
    if (new Date(e.ts).getTime() < cutoff && e.id !== undefined) {
      const { remove } = await import("./idb");
      await remove(STORE, e.id);
      removed += 1;
    }
  }
  return removed;
}

/** Build a CSV blob of the audit entries (consumed by the tray export). */
export function toCsv(entries: AuditEntry[]): string {
  const header = "ts,kind,mutation_id,endpoint,error_code";
  const rows = entries.map(
    (e) =>
      `${e.ts},${e.kind},${e.mutation_id},${e.endpoint},${e.error_code ?? ""}`
  );
  return [header, ...rows].join("\n");
}
