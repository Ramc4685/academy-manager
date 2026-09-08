import { beforeEach, describe, expect, it, vi } from "vitest";

import type { QueuedMutation } from "./queue";

// In-memory stand-in for the IndexedDB-backed queue so the attendance view
// over it can be exercised without a browser.
const store = new Map<string, QueuedMutation>();

vi.mock("./queue", () => ({
  enqueue: async (m: Omit<QueuedMutation, "status" | "attempts" | "created_at">) => {
    const full: QueuedMutation = {
      ...m,
      status: "queued",
      attempts: 0,
      created_at: new Date().toISOString(),
    };
    store.set(full.mutation_id, full);
    return full;
  },
  listQueued: async () =>
    [...store.values()].filter((m) => m.status === "queued" || m.status === "in_flight"),
  update: async (m: QueuedMutation) => {
    store.set(m.mutation_id, m);
  },
  dropById: async (mutation_id: string) => {
    store.delete(mutation_id);
  },
}));

import { queueMark, queuedMarksFor } from "./attendance-queue";

const base = {
  occurrence_id: "occ-1",
  session_id: "s-1",
  client_app_version: "test",
} as const;

describe("queueMark", () => {
  beforeEach(() => store.clear());

  it("enqueues a first mark with the mutation id inside the payload", async () => {
    const m = await queueMark({ ...base, student_id: "st1", status: "present" });
    expect(m.status).toBe("queued");
    expect(m.endpoint).toBe("/coach/attendance");
    expect(m.payload).toMatchObject({
      mutation_id: m.mutation_id,
      occurrence_id: "occ-1",
      session_id: "s-1",
      student_id: "st1",
      status: "present",
      client_app_version: "test",
    });
    expect(typeof m.payload.marked_at_client).toBe("string");
    expect(store.size).toBe(1);
  });

  it("rewrites a fresh queued mark in place, keeping the same mutation id", async () => {
    // Never sent (queued, zero attempts) → the id cannot be cached server-side,
    // so reusing it is safe and keeps one queued mark per student.
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    const second = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(second.mutation_id).toBe(first.mutation_id);
    expect(second.payload.status).toBe("absent");
    expect(store.size).toBe(1);
    expect(store.get(first.mutation_id)?.payload.status).toBe("absent");
  });

  it("gives an already-attempted mark a NEW id and drops the old entry", async () => {
    // sync.ts leaves a mark `queued` with attempts === MAX_ATTEMPTS after five
    // failures. Any attempt > 0 may have committed server-side without the
    // response reaching us, and MarkAttendance is @idempotent on mutation_id —
    // a replay under the same id would return the CACHED old status. So the
    // new intent must travel under a fresh key, with a fresh retry budget.
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    store.set(first.mutation_id, {
      ...first,
      attempts: 5,
      last_attempt_at: "2026-09-06T10:00:00.000Z",
    });
    const again = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(again.mutation_id).not.toBe(first.mutation_id);
    expect(again.attempts).toBe(0);
    expect(again.last_attempt_at).toBeUndefined();
    expect(again.payload.status).toBe("absent");
    expect(again.payload.mutation_id).toBe(again.mutation_id);
    // Exactly one queued mark for this student, and it is the new one.
    expect(store.has(first.mutation_id)).toBe(false);
    expect(store.size).toBe(1);
  });

  it("gives a mark the sync has claimed (in_flight) a NEW id", async () => {
    // The tap landed while syncNow was replaying this mutation. Rewriting the
    // payload in place would be sent-and-deleted with the OLD status.
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    store.set(first.mutation_id, { ...first, status: "in_flight" });
    const again = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(again.mutation_id).not.toBe(first.mutation_id);
    expect(again.status).toBe("queued");
    expect(again.payload.status).toBe("absent");
    expect(store.has(first.mutation_id)).toBe(false);
    expect(store.size).toBe(1);
  });

  it("keeps separate mutations for different students and occurrences", async () => {
    await queueMark({ ...base, student_id: "st1", status: "present" });
    await queueMark({ ...base, student_id: "st2", status: "present" });
    await queueMark({ ...base, occurrence_id: "occ-2", student_id: "st1", status: "absent" });
    expect(store.size).toBe(3);
  });

  it("does not rewrite a mutation that already failed into the tray", async () => {
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    store.set(first.mutation_id, { ...first, status: "needs_review" });
    const again = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(again.mutation_id).not.toBe(first.mutation_id);
    expect(store.size).toBe(2);
  });
});

describe("queuedMarksFor", () => {
  beforeEach(() => store.clear());

  it("returns the queued status per student for one occurrence only", async () => {
    const a = await queueMark({ ...base, student_id: "st1", status: "present" });
    const b = await queueMark({ ...base, student_id: "st2", status: "absent" });
    await queueMark({ ...base, occurrence_id: "occ-2", student_id: "st3", status: "present" });

    expect(await queuedMarksFor("occ-1")).toEqual({
      st1: { status: "present", mutation_id: a.mutation_id },
      st2: { status: "absent", mutation_id: b.mutation_id },
    });
    expect(await queuedMarksFor("occ-9")).toEqual({});
  });

  it("ignores tray items and other endpoints", async () => {
    const a = await queueMark({ ...base, student_id: "st1", status: "present" });
    store.set(a.mutation_id, { ...a, status: "needs_review" });
    expect(await queuedMarksFor("occ-1")).toEqual({});
  });
});
