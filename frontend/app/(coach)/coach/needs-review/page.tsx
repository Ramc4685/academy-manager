"use client";

import { useEffect, useState } from "react";

import { listAudit, recordAudit, toCsv } from "@/lib/offline/audit";
import { correctAttendance } from "@/lib/api/coach";
import { attendanceConflict, describeQueuedMutation } from "@/lib/offline/mutation-label";
import {
  dropById,
  getById,
  listNeedsReview,
  update,
  type QueuedMutation,
} from "@/lib/offline/queue";
import { onSync, syncNow } from "@/lib/offline/sync";
import { RetryButton } from "@/components/coach/RetryButton";
import { useIsNativeApp } from "@/lib/use-native-app";

/**
 * Coach's "Needs review" tray.
 *
 * Lists mutations that failed with a domain error (4xx) and were therefore
 * not applied server-side. For each entry the coach can retry, dismiss, export
 * their audit log, or — for case #4 (two-device same student) — pick which
 * mark to keep: the recorded one, or theirs (sent as a correction, since
 * replaying the same first mark would only 409 again).
 */

export default function NeedsReviewPage() {
  const [items, setItems] = useState<QueuedMutation[]>([]);
  const [loading, setLoading] = useState(true);
  const isNativeApp = useIsNativeApp();
  const [retrying, setRetrying] = useState<string | null>(null);
  const [choiceError, setChoiceError] = useState<Record<string, string>>({});

  async function refresh() {
    setItems(await listNeedsReview());
    setLoading(false);
  }

  useEffect(() => {
    void refresh();
  }, []);

  // The sync loop writes the queue from outside React (an auto-sync on
  // reconnect, or the run a Retry kicks off), so the tray follows it instead
  // of stranding the coach on a list that needs a manual reload to be true.
  useEffect(() => {
    return onSync((e) => {
      if (e.kind === "finished" || e.kind === "paused") void refresh();
    });
  }, []);

  /**
   * Put a failed mark back in the outbox and send it again (#895).
   *
   * Deliberately the SAME record: same `mutation_id` — which is also the
   * server's idempotency key — and the same payload, flipped back to `queued`
   * so the existing sync loop picks it up. Nothing new is enqueued, so a
   * retry can never double-apply a mark the server did commit; it replays and
   * the server answers with the original result. `attempts` resets because the
   * coach's tap is a fresh decision, not a continuation of the run that gave
   * up.
   */
  async function retry(m: QueuedMutation) {
    setRetrying(m.mutation_id);
    try {
      // Re-read: the record may have been dropped or rewritten since this
      // list was rendered, and resurrecting a stale copy would send an intent
      // the coach has already replaced.
      const current = await getById(m.mutation_id);
      if (!current) {
        await refresh();
        return;
      }
      const requeued: QueuedMutation = {
        ...current,
        status: "queued",
        attempts: 0,
      };
      delete requeued.error;
      await update(requeued);
      await recordAudit({
        kind: "retried",
        mutation_id: m.mutation_id,
        endpoint: m.endpoint,
        error_code: m.error?.code,
        ts: new Date().toISOString(),
      });
      await refresh();
      await syncNow();
    } finally {
      setRetrying(null);
      await refresh();
    }
  }

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

  /** Case #4: replace the recorded mark with the one queued on this phone. */
  async function keepMine(m: QueuedMutation) {
    const conflict = attendanceConflict(m);
    if (!conflict) return;
    setRetrying(m.mutation_id);
    try {
      await correctAttendance(conflict.occurrence_id, conflict.student_id, {
        status: conflict.mine as "present" | "absent" | "late",
        reason: "coach kept the mark queued on their phone",
      });
      await dropById(m.mutation_id);
      await recordAudit({
        kind: "synced",
        mutation_id: m.mutation_id,
        endpoint: m.endpoint,
        error_code: m.error?.code,
        ts: new Date().toISOString(),
      });
    } catch (err) {
      setChoiceError((prev) => ({
        ...prev,
        [m.mutation_id]:
          (err as { code?: string }).code === "Coaching.CorrectionWindowExpired"
            ? "This mark is older than 48 hours, so only an admin can change it."
            : "Couldn’t change the mark. Try again in a moment.",
      }));
    } finally {
      setRetrying(null);
      await refresh();
    }
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
        {!isNativeApp && (
          <button
            onClick={() => void exportCsv()}
            className="min-h-touch rounded-md border border-neutral-300 px-3 text-sm dark:border-neutral-700"
          >
            Export audit
          </button>
        )}
      </header>

      {loading && <p className="text-neutral-500">Loading…</p>}

      {!loading && items.length === 0 && (
        <p data-testid="tray-empty" className="text-neutral-500">
          Everything is synced. This list only holds attendance marks that did not save on
          this phone. To write a class recap, open the class and tap Class recap.
        </p>
      )}

      <ul className="space-y-3" data-testid="tray-list">
        {items.map((m) => (
          <li
            key={m.mutation_id}
            data-testid={`tray-${m.mutation_id}`}
            className="rounded-lg border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950"
          >
            <p className="font-medium">{describeQueuedMutation(m)}</p>
            <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-400">
              {reviewReason(m)}
            </p>
            {choiceError[m.mutation_id] && (
              <p role="alert" className="mt-1 text-xs text-red-700">
                {choiceError[m.mutation_id]}
              </p>
            )}
            {attendanceConflict(m) ? (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={retrying !== null}
                  data-testid={`tray-keep-recorded-${m.mutation_id}`}
                  onClick={() => void dismiss(m)}
                  className="min-h-touch rounded-md border border-amber-300 px-3 text-sm disabled:opacity-50 dark:border-amber-700"
                >
                  Keep {attendanceConflict(m)!.recorded}
                </button>
                <button
                  type="button"
                  disabled={retrying !== null}
                  data-testid={`tray-use-mine-${m.mutation_id}`}
                  onClick={() => void keepMine(m)}
                  className="min-h-touch rounded-md border border-amber-300 px-3 text-sm font-semibold disabled:opacity-50 dark:border-amber-700"
                >
                  Change to {attendanceConflict(m)!.mine}
                </button>
              </div>
            ) : (
              <div className="mt-3 flex flex-wrap gap-2">
                {/*
                  The action ids deliberately do NOT extend the row's own
                  `tray-<id>` prefix, so a prefix match for rows never picks up
                  an action (see e2e/helpers/row-actions.ts).
                */}
                <RetryButton
                  disabled={retrying !== null}
                  busy={retrying === m.mutation_id}
                  testId={`tray-retry-${m.mutation_id}`}
                  onClick={() => void retry(m)}
                />
                <button
                  type="button"
                  disabled={retrying !== null}
                  data-testid={`tray-dismiss-${m.mutation_id}`}
                  onClick={() => void dismiss(m)}
                  className="min-h-touch rounded-md border border-amber-300 px-3 text-sm disabled:opacity-50 dark:border-amber-700"
                >
                  Dismiss
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

// Plain-language reasons keyed by the queue's internal error code. The raw code
// and backend message are never shown to the coach — only the friendly reason.
const REVIEW_REASONS: Record<string, string> = {
  "Coaching.SessionCancelled": "This class date was cancelled, so your mark wasn’t saved.",
  "Coaching.StudentNotEnrolled":
    "This student is no longer enrolled in the class, so your mark wasn’t saved.",
  "Coaching.ConflictAttendanceExists":
    "Attendance was already recorded for this student, so your mark wasn’t applied.",
  "Coaching.OccurrenceNotStarted": "That class hadn’t started yet, so your mark wasn’t saved.",
  "Coaching.SessionNotAssigned":
    "This class isn’t assigned to you for that date, so your mark wasn’t saved.",
};

function reviewReason(m: QueuedMutation): string {
  const conflict = attendanceConflict(m);
  if (conflict) {
    return `Already recorded as ${conflict.recorded}; you marked ${conflict.mine}. Which should stand?`;
  }
  const code = m.error?.code;
  if (code && REVIEW_REASONS[code]) return REVIEW_REASONS[code];
  return "This change couldn’t be saved. Retry it, or dismiss it and mark again from the class.";
}
