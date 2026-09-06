"use client";

import { ulid } from "ulid";

import type { AttendanceStatus, MarkAttendanceRequest } from "@/lib/api/coach";
import { enqueue, listQueued, update, type QueuedMutation } from "./queue";

/**
 * Attendance-specific view over the offline mutation queue (lib/offline/queue.ts).
 *
 * Only FIRST marks are queued: the queue replays `POST /coach/attendance`,
 * and a correction of a server-saved mark would only 409 into the tray
 * (docs/offline-policy.md). A second tap on the same student while offline
 * rewrites the queued mutation in place — policy case #1, last write wins
 * on the device — so one student never has two queued marks.
 */

export interface QueueMarkInput {
  occurrence_id: string;
  session_id: string;
  student_id: string;
  status: AttendanceStatus;
  client_app_version: string;
}

export interface QueuedMark {
  status: AttendanceStatus;
  mutation_id: string;
}

type AttendancePayload = MarkAttendanceRequest & Record<string, unknown>;

function isMarkFor(m: QueuedMutation, occurrenceId: string): m is QueuedMutation & {
  payload: AttendancePayload;
} {
  if (m.endpoint !== "/coach/attendance") return false;
  const p = m.payload as Partial<AttendancePayload>;
  return p.occurrence_id === occurrenceId && typeof p.student_id === "string";
}

/**
 * Queue a first mark for a student, or rewrite the one already queued for
 * the same occurrence + student. Resolves with the stored mutation; its
 * `mutation_id` is also the server idempotency key inside the payload.
 */
export async function queueMark(input: QueueMarkInput): Promise<QueuedMutation> {
  const marked_at_client = new Date().toISOString();
  const existing = (await listQueued()).find(
    (m) =>
      m.status === "queued" &&
      isMarkFor(m, input.occurrence_id) &&
      m.payload.student_id === input.student_id,
  );
  if (existing) {
    // A fresh tap is a new intent: reset the retry budget so a mark the sync
    // already paused (MAX_ATTEMPTS transient failures, lib/offline/sync.ts)
    // is sent again instead of being skipped forever.
    const rewritten: QueuedMutation = {
      ...existing,
      attempts: 0,
      payload: {
        ...existing.payload,
        session_id: input.session_id,
        status: input.status,
        marked_at_client,
        client_app_version: input.client_app_version,
      },
    };
    delete rewritten.last_attempt_at;
    await update(rewritten);
    return rewritten;
  }
  const mutation_id = ulid();
  const payload: AttendancePayload = {
    mutation_id,
    occurrence_id: input.occurrence_id,
    session_id: input.session_id,
    student_id: input.student_id,
    status: input.status,
    marked_at_client,
    client_app_version: input.client_app_version,
  };
  return enqueue({ mutation_id, endpoint: "/coach/attendance", payload });
}

/** Marks still waiting on the device for one occurrence, keyed by student. */
export async function queuedMarksFor(occurrenceId: string): Promise<Record<string, QueuedMark>> {
  const out: Record<string, QueuedMark> = {};
  for (const m of await listQueued()) {
    if (!isMarkFor(m, occurrenceId)) continue;
    out[m.payload.student_id] = { status: m.payload.status, mutation_id: m.mutation_id };
  }
  return out;
}
