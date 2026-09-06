"use client";

import { apiFetch } from "@/lib/api/client";
import { recordAudit } from "./audit";
import { dropById, getById, list, listQueued, type QueuedMutation, update } from "./queue";

/**
 * Offline mutation sync orchestrator.
 *
 * Per docs/offline-policy.md:
 * - Serial per device.
 * - Retry 5xx + network errors with backoff 1/4/16/60s (cap 60s).
 * - 4xx domain errors → `needs_review` ("tray") with structured code.
 * - Idempotent on `mutation_id` server-side; replays return original result.
 */

const RETRY_DELAYS_MS = [0, 1_000, 4_000, 16_000, 60_000];
const MAX_ATTEMPTS = RETRY_DELAYS_MS.length;

type SyncEvent =
  | { kind: "started"; total: number }
  | { kind: "succeeded"; mutation: QueuedMutation }
  | { kind: "needs_review"; mutation: QueuedMutation }
  | { kind: "transient_error"; mutation: QueuedMutation; remaining: number }
  | { kind: "paused"; reason: string }
  | { kind: "finished"; processed: number; tray: number };

export type SyncListener = (e: SyncEvent) => void;

let _running = false;
const _listeners = new Set<SyncListener>();

export function onSync(listener: SyncListener): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

function emit(e: SyncEvent): void {
  for (const l of _listeners) l(e);
}

export async function syncNow(): Promise<void> {
  if (_running) return;
  _running = true;
  try {
    const queue = await listQueued();
    emit({ kind: "started", total: queue.length });
    let processed = 0;
    let tray = 0;

    for (const m of queue) {
      const outcome = await sendOne(m);
      if (outcome === "succeeded") processed += 1;
      if (outcome === "needs_review") tray += 1;
      // "superseded": a fresh tap replaced this mutation while it was in
      // flight. Nothing to count and nothing to write back — the replacement
      // is already in the queue and goes out on the next run.
      if (outcome === "paused") {
        emit({ kind: "paused", reason: "max attempts exceeded in this run" });
        break;
      }
    }

    emit({ kind: "finished", processed, tray });
  } finally {
    _running = false;
  }
}

type SendOutcome = "succeeded" | "needs_review" | "paused" | "superseded";

/**
 * Merge a few fields into the stored copy of a mutation, re-reading it first.
 *
 * `syncNow` iterates a snapshot taken at run start, so writing `{...snapshot}`
 * back would resurrect a record a fresh coach tap has since dropped, or clobber
 * a payload it rewrote. Returns null when the record is gone — the caller must
 * then leave it alone.
 */
async function patchRecord(
  mutation_id: string,
  fields: Partial<Pick<QueuedMutation, "status" | "attempts" | "last_attempt_at" | "error">>,
): Promise<QueuedMutation | null> {
  const current = await getById(mutation_id);
  if (!current) return null;
  const next: QueuedMutation = { ...current, ...fields };
  await update(next);
  return next;
}

async function sendOne(snapshot: QueuedMutation): Promise<SendOutcome> {
  // Claim the mutation for this run BEFORE the first POST. `queueMark` treats
  // an `in_flight` record as un-rewritable, so a tap that lands while we are
  // replaying enqueues a NEW mutation with its own idempotency key instead of
  // mutating the payload we are about to send (or one the server may already
  // have committed under this id).
  const m = await patchRecord(snapshot.mutation_id, { status: "in_flight" });
  if (!m) return "superseded";
  let attempt = m.attempts;
  while (attempt < MAX_ATTEMPTS) {
    if (RETRY_DELAYS_MS[attempt] > 0) {
      await new Promise((r) => setTimeout(r, RETRY_DELAYS_MS[attempt]));
    }
    attempt += 1;
    try {
      await apiFetch(m.endpoint, {
        method: "POST",
        body: JSON.stringify(m.payload),
      });
      await dropById(m.mutation_id);
      await recordAudit({
        kind: "synced",
        mutation_id: m.mutation_id,
        endpoint: m.endpoint,
        ts: new Date().toISOString(),
      });
      emit({ kind: "succeeded", mutation: { ...m, status: "queued", attempts: attempt } });
      return "succeeded";
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (typeof status === "number" && status >= 400 && status < 500) {
        // Domain error — move to tray, unless a fresh tap already replaced it.
        const updated = await patchRecord(m.mutation_id, {
          status: "needs_review",
          attempts: attempt,
          last_attempt_at: new Date().toISOString(),
          error: {
            code: (err as { code?: string }).code ?? "Unknown",
            message: (err as { message?: string }).message ?? "Unknown",
            details: (err as { details?: Record<string, unknown> }).details,
          },
        });
        if (!updated) return "superseded";
        await recordAudit({
          kind: "needs_review",
          mutation_id: m.mutation_id,
          endpoint: m.endpoint,
          error_code: updated.error?.code,
          ts: new Date().toISOString(),
        });
        emit({ kind: "needs_review", mutation: updated });
        return "needs_review";
      }
      // Transient (5xx, network) — try again.
      emit({
        kind: "transient_error",
        mutation: { ...m, attempts: attempt },
        remaining: MAX_ATTEMPTS - attempt,
      });
    }
  }
  // Max attempts hit without success — surface as paused; release the claim so
  // the mark is `queued` again (and picked up by the next run) without
  // overwriting anything a concurrent tap changed.
  const released = await patchRecord(m.mutation_id, {
    status: "queued",
    attempts: attempt,
    last_attempt_at: new Date().toISOString(),
  });
  if (!released) return "superseded";
  return "paused";
}

/** Wire `online` to auto-sync. Call once in the coach layout. */
export function startAutoSync(): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = () => void syncNow();
  window.addEventListener("online", handler);
  // Kick once on mount in case we mounted online with queued items.
  void list().then((items) => {
    // `in_flight` too: a run killed mid-replay (tab closed, reload) leaves its
    // claim behind, and that mark still has to go out.
    if (items.some((m) => m.status === "queued" || m.status === "in_flight") && navigator.onLine) {
      void syncNow();
    }
  });
  return () => window.removeEventListener("online", handler);
}
