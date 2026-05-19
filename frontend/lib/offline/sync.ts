"use client";

import { apiFetch } from "@/lib/api/client";
import { recordAudit } from "./audit";
import { dropById, list, listQueued, type QueuedMutation, update } from "./queue";

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

async function sendOne(m: QueuedMutation): Promise<"succeeded" | "needs_review" | "paused"> {
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
        // Domain error — move to tray.
        const updated: QueuedMutation = {
          ...m,
          status: "needs_review",
          attempts: attempt,
          last_attempt_at: new Date().toISOString(),
          error: {
            code: (err as { code?: string }).code ?? "Unknown",
            message: (err as { message?: string }).message ?? "Unknown",
            details: (err as { details?: Record<string, unknown> }).details,
          },
        };
        await update(updated);
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
  // Max attempts hit without success — surface as paused; remains in queue.
  await update({ ...m, attempts: attempt, last_attempt_at: new Date().toISOString() });
  return "paused";
}

/** Wire `online` to auto-sync. Call once in the coach layout. */
export function startAutoSync(): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = () => void syncNow();
  window.addEventListener("online", handler);
  // Kick once on mount in case we mounted online with queued items.
  void list().then((items) => {
    if (items.some((m) => m.status === "queued") && navigator.onLine) {
      void syncNow();
    }
  });
  return () => window.removeEventListener("online", handler);
}
