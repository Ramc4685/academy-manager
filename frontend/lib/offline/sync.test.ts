import { beforeEach, describe, expect, it, vi } from "vitest";

import type { QueuedMutation } from "./queue";

/**
 * Interplay between `syncNow` and a coach tap that lands while a mark is being
 * replayed. `syncNow` iterates a snapshot taken at run start, so every
 * write-back has to go through the live store or it silently loses the tap.
 */

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
  list: async () => [...store.values()],
  listQueued: async () =>
    [...store.values()].filter((m) => m.status === "queued" || m.status === "in_flight"),
  update: async (m: QueuedMutation) => {
    store.set(m.mutation_id, m);
  },
  dropById: async (mutation_id: string) => {
    store.delete(mutation_id);
  },
  getById: async (mutation_id: string) => store.get(mutation_id) ?? null,
}));

const apiFetch = vi.fn();
vi.mock("@/lib/api/client", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));
vi.mock("./audit", () => ({ recordAudit: async () => undefined }));

import { queueMark } from "./attendance-queue";
import { syncNow } from "./sync";

const base = {
  occurrence_id: "occ-1",
  session_id: "s-1",
  client_app_version: "test",
} as const;

function only(): QueuedMutation {
  const items = [...store.values()];
  expect(items).toHaveLength(1);
  return items[0];
}

describe("syncNow", () => {
  beforeEach(() => {
    store.clear();
    apiFetch.mockReset();
  });

  it("claims the mutation as in_flight before the first POST", async () => {
    const queued = await queueMark({ ...base, student_id: "st1", status: "present" });
    let statusAtSend: string | undefined;
    apiFetch.mockImplementation(async () => {
      statusAtSend = store.get(queued.mutation_id)?.status;
      return {};
    });

    await syncNow();

    expect(statusAtSend).toBe("in_flight");
    expect(store.size).toBe(0); // sent and dropped
  });

  it("keeps a tap that lands mid-replay instead of sending and deleting it", async () => {
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    apiFetch.mockImplementation(async () => {
      // The coach re-taps while this mutation is in flight.
      await queueMark({ ...base, student_id: "st1", status: "absent" });
      return {};
    });

    await syncNow();

    expect(apiFetch).toHaveBeenCalledTimes(1);
    const survivor = only();
    expect(survivor.mutation_id).not.toBe(first.mutation_id);
    expect(survivor.status).toBe("queued");
    expect(survivor.payload.status).toBe("absent");
  });

  it("does not resurrect a superseded mutation when the replay 4xxs", async () => {
    const first = await queueMark({ ...base, student_id: "st1", status: "present" });
    apiFetch.mockImplementation(async () => {
      await queueMark({ ...base, student_id: "st1", status: "absent" });
      throw Object.assign(new Error("conflict"), {
        status: 409,
        code: "Coaching.ConflictAttendanceExists",
      });
    });

    await syncNow();

    const survivor = only();
    expect(survivor.mutation_id).not.toBe(first.mutation_id);
    expect(survivor.status).toBe("queued");
    expect(survivor.error).toBeUndefined();
  });

  it("releases an exhausted mutation back to queued rather than leaving it claimed", async () => {
    const queued = await queueMark({ ...base, student_id: "st1", status: "present" });
    // Five transient failures already burned the retry budget.
    store.set(queued.mutation_id, { ...queued, attempts: 5 });

    await syncNow();

    expect(apiFetch).not.toHaveBeenCalled();
    const released = only();
    expect(released.status).toBe("queued");
    expect(released.attempts).toBe(5);
    expect(released.last_attempt_at).toBeTruthy();
  });
});
