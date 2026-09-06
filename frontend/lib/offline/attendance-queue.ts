"use client";

import { ulid } from "ulid";

import type { AttendanceStatus, MarkAttendanceRequest } from "@/lib/api/coach";
import { dropById, enqueue, listQueued, update, type QueuedMutation } from "./queue";

/**
 * Attendance-specific view over the offline mutation queue (lib/offline/queue.ts).
 *
 * Only FIRST marks are queued: the queue replays `POST /coach/attendance`,
 * and a correction of a server-saved mark would only 409 into the tray
 * (docs/offline-policy.md). A second tap on the same student while offline
 * replaces the queued mutation — policy case #1, last write wins on the
 * device — so one student never has two queued marks.
 *
 * "Replaces" is in-place only while the mutation is provably un-sent
 * (`queued` with zero attempts). Once the sync has claimed it (`in_flight`) or
 * tried it at least once, the POST may already have committed server-side, and
 * `MarkAttendance` is `@idempotent` on `mutation_id`: a replay under the same
 * id would return the CACHED old status while the row shows the new one. So a
 * tap on an already-attempted mark drops the old entry and enqueues a fresh
 * ULID instead. The coach's latest intent is always what goes to the server; if
 * the earlier attempt did commit, the new one 409s into the Needs-review tray
 * where the coach can see it, rather than vanishing.
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
 * Queue a first mark for a student, replacing the one already queued for the
 * same occurrence + student. Resolves with the stored mutation; its
 * `mutation_id` is also the server idempotency key inside the payload.
 */
export async function queueMark(input: QueueMarkInput): Promise<QueuedMutation> {
  const marked_at_client = new Date().toISOString();
  // `listQueued` covers `queued` and `in_flight`; a `needs_review` mark is the
  // coach's to resolve in the tray and is never touched here.
  const existing = (await listQueued()).find(
    (m) =>
      isMarkFor(m, input.occurrence_id) && m.payload.student_id === input.student_id,
  );
  if (existing && existing.status === "queued" && existing.attempts === 0) {
    // Provably un-sent: safe to rewrite in place under the same id.
    const rewritten: QueuedMutation = {
      ...existing,
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
  if (existing) {
    // In flight, or already attempted at least once: the server may hold this
    // id. Drop it and send the new intent under a fresh idempotency key.
    await dropById(existing.mutation_id);
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
