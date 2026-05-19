"use client";

import { useEffect, useState } from "react";

import { listAudit, recordAudit, toCsv } from "@/lib/offline/audit";
import { dropById, listNeedsReview, type QueuedMutation } from "@/lib/offline/queue";

/**
 * Coach's "Needs review" tray.
 *
 * Lists mutations that failed with a domain error (4xx) and were therefore
 * not applied server-side. For each entry the coach can dismiss, export
 * their audit log, or — for case #4 (two-device same student) — pick which
 * device's mark to keep.
 */

export default function NeedsReviewPage() {
  const [items, setItems] = useState<QueuedMutation[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setItems(await listNeedsReview());
    setLoading(false);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function dismiss(m: QueuedMutation) {
    await dropById(m.mutation_id);
    await recordAudit({
      kind: "dismissed",
      mutation_id: m.mutation_id,
      endpoint: m.endpoint,
      error_code: m.error?.code,
      ts: new Date().toISOString(),
    });
    await refresh();
  }

  async function exportCsv() {
    const audit = await listAudit();
    const csv = toCsv(audit);
    await recordAudit({
      kind: "exported",
      mutation_id: "—",
      endpoint: "—",
      ts: new Date().toISOString(),
    });
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `coach-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section data-testid="needs-review">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Needs review</h1>
        <button
          onClick={() => void exportCsv()}
          className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700"
        >
          Export audit
        </button>
      </header>

      {loading && <p className="text-neutral-500">Loading…</p>}

      {!loading && items.length === 0 && (
        <p data-testid="tray-empty" className="text-neutral-500">
          Everything is synced.
        </p>
      )}

      <ul className="space-y-3" data-testid="tray-list">
        {items.map((m) => (
          <li
            key={m.mutation_id}
            data-testid={`tray-${m.mutation_id}`}
            className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950"
          >
            <p className="font-medium">{describe(m)}</p>
            <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
              {m.error?.code}: {m.error?.message}
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => void dismiss(m)}
                className="min-h-touch rounded-md border border-amber-300 px-3 text-sm dark:border-amber-700"
              >
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function describe(m: QueuedMutation): string {
  const p = m.payload as { student_id?: string; status?: string; session_id?: string };
  return `Mark ${p.status ?? "?"} for ${p.student_id ?? "?"} in ${p.session_id ?? "?"}`;
}
