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

  it("rewrites the queued mark for the same student instead of adding a second one", async () => {
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    const second = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(second.mutation_id).toBe(first.mutation_id);
    expect(second.payload.status).toBe("absent");
    expect(store.size).toBe(1);
    expect(store.get(first.mutation_id)?.payload.status).toBe("absent");
  });

  it("resets the retry budget when a paused mark is rewritten", async () => {
    // sync.ts leaves a mark `queued` with attempts === MAX_ATTEMPTS after five
    // transient failures and then skips it on every later run. A fresh tap
    // must give it a new budget or the QUEUED chip is permanent.
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    store.set(first.mutation_id, {
      ...first,
      attempts: 5,
      last_attempt_at: "2026-09-06T10:00:00.000Z",
    });
    const again = await queueMark({ ...base, student_id: "st1", status: "absent" });
    expect(again.mutation_id).toBe(first.mutation_id);
    expect(again.attempts).toBe(0);
    expect(again.last_attempt_at).toBeUndefined();
    const stored = store.get(first.mutation_id);
    expect(stored?.attempts).toBe(0);
    expect(stored?.last_attempt_at).toBeUndefined();
    expect(stored?.payload.status).toBe("absent");
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
