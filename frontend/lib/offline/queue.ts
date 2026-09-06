"use client";

import { getAll, put, remove } from "./idb";

/**
 * IndexedDB-backed mutation queue for offline attendance writes.
 *
 * Append-only, keyed by client ULID (`mutation_id`). Survives reload and
 * browser restart. See docs/offline-policy.md.
 */

export type QueuedStatus = "queued" | "in_flight" | "needs_review";

export interface QueuedMutation {
  mutation_id: string;            // ULID — also the server idempotency key
  endpoint: "/coach/attendance";  // single endpoint for Wave 1B
  payload: Record<string, unknown>;
  status: QueuedStatus;
  attempts: number;
  created_at: string;             // ISO
  last_attempt_at?: string;
  error?: { code: string; message: string; details?: Record<string, unknown> };
}

const STORE = "mutations" as const;

export async function enqueue(m: Omit<QueuedMutation, "status" | "attempts" | "created_at">): Promise<QueuedMutation> {
  const full: QueuedMutation = {
    ...m,
    status: "queued",
    attempts: 0,
    created_at: new Date().toISOString(),
  };
  await put(STORE, full);
  return full;
}

export async function list(): Promise<QueuedMutation[]> {
  const items = await getAll<QueuedMutation>(STORE);
  return items.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export async function listQueued(): Promise<QueuedMutation[]> {
  return (await list()).filter((m) => m.status === "queued" || m.status === "in_flight");
}

export async function listNeedsReview(): Promise<QueuedMutation[]> {
  return (await list()).filter((m) => m.status === "needs_review");
}

export async function update(m: QueuedMutation): Promise<void> {
  await put(STORE, m);
}

/**
 * Re-read one mutation by id. Returns null when it is no longer in the store —
 * which is how a writer learns that a fresh coach tap superseded (and dropped)
 * the record it was holding, so it must not write a stale copy back.
 */
export async function getById(mutation_id: string): Promise<QueuedMutation | null> {
  const items = await getAll<QueuedMutation>(STORE);
  return items.find((m) => m.mutation_id === mutation_id) ?? null;
}

export async function dropById(mutation_id: string): Promise<void> {
  await remove(STORE, mutation_id);
}

const MAX_QUEUE = 200;

export async function trimIfFull(): Promise<number> {
  const items = await list();
  if (items.length <= MAX_QUEUE) return 0;
  const toDrop = items
    .filter((m) => m.status !== "needs_review") // never drop tray items silently
    .slice(0, items.length - MAX_QUEUE);
  for (const m of toDrop) await dropById(m.mutation_id);
  return toDrop.length;
}
