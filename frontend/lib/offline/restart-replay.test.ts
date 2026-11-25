import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A queued mark must survive an app restart and reach the server exactly once.
 *
 * The real queue lives in IndexedDB (./idb). Here the IndexedDB stand-in is a
 * Map that outlives `vi.resetModules()`, so "restart" means: every offline
 * module is loaded fresh (no in-memory state carries over, as after the app is
 * killed) while the device store keeps what was written. The fake server is
 * idempotent on `mutation_id`, like `MarkAttendance`.
 */

const disk = vi.hoisted(() => ({
  stores: { mutations: new Map<string, unknown>(), audit: new Map<string, unknown>() },
  seq: 0,
}));

vi.mock("./idb", () => ({
  put: async (store: "mutations" | "audit", value: Record<string, unknown>) => {
    const key = store === "mutations" ? String(value.mutation_id) : String((disk.seq += 1));
    disk.stores[store].set(key, structuredClone(value));
  },
  getAll: async (store: "mutations" | "audit") =>
    [...disk.stores[store].values()].map((v) => structuredClone(v)),
  remove: async (store: "mutations" | "audit", key: string) => {
    disk.stores[store].delete(key);
  },
  clearStore: async (store: "mutations" | "audit") => {
    disk.stores[store].clear();
  },
}));

const server = vi.hoisted(() => ({
  /** mutation_id → stored mark; one row per id, like the idempotency store. */
  rows: new Map<string, Record<string, unknown>>(),
  posts: 0,
  /** When set, the server commits the mark but the reply never arrives. */
  dropReply: false,
}));

vi.mock("@/lib/api/client", () => ({
  apiFetch: async (_path: string, init: { body: string }) => {
    server.posts += 1;
    const body = JSON.parse(init.body) as Record<string, unknown>;
    const id = String(body.mutation_id);
    if (!server.rows.has(id)) server.rows.set(id, body);
    if (server.dropReply) throw Object.assign(new Error("network"), { status: undefined });
    return server.rows.get(id);
  },
}));

vi.mock("./owner", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./owner")>()),
  currentOwner: () => null,
}));

async function bootApp() {
  vi.resetModules();
  const queue = await import("./attendance-queue");
  const sync = await import("./sync");
  return { ...queue, ...sync };
}

const mark = {
  occurrence_id: "occ-1",
  session_id: "s-1",
  student_id: "st1",
  status: "present" as const,
  client_app_version: "test",
};

// Each test re-imports the queue modules; under a loaded full run that alone can
// pass 5s, and a timed-out test leaks its sync into the next one.
describe("offline attendance across an app restart", { timeout: 30_000 }, () => {
  beforeEach(() => {
    disk.stores.mutations.clear();
    disk.stores.audit.clear();
    server.rows.clear();
    server.posts = 0;
    server.dropReply = false;
  });

  it("keeps a mark queued offline after a restart and sends it once on reconnect", async () => {
    const first = await bootApp();
    const queued = await first.queueMark(mark);
    expect(server.posts).toBe(0);

    // App killed and reopened: fresh modules, same device store.
    const second = await bootApp();
    expect(await second.queuedMarksFor("occ-1")).toEqual({
      st1: { status: "present", mutation_id: queued.mutation_id },
    });

    await second.syncNow();
    await second.syncNow(); // a second reconnect finds nothing left to send

    expect(server.posts).toBe(1);
    expect([...server.rows.keys()]).toEqual([queued.mutation_id]);
    expect(await second.queuedMarksFor("occ-1")).toEqual({});
  });

  it("replays a mark whose reply was lost under the same key, leaving one mark", async () => {
    const first = await bootApp();
    const queued = await first.queueMark(mark);
    // The server commits the mark but no reply ever arrives: the sync keeps
    // retrying (same payload), gives up for this run, and the app closes.
    server.dropReply = true;
    vi.useFakeTimers();
    const run = first.syncNow();
    await vi.runAllTimersAsync();
    await run;
    vi.useRealTimers();
    expect(server.posts).toBeGreaterThan(1);
    expect(server.rows.size).toBe(1);
    // A run killed mid-send leaves its claim behind; the next start must still send it.
    const stored = disk.stores.mutations.get(queued.mutation_id) as Record<string, unknown>;
    disk.stores.mutations.set(queued.mutation_id, { ...stored, status: "in_flight" });

    server.dropReply = false;
    const second = await bootApp();
    await second.syncNow();

    // Every POST carried the same idempotency key, so the server holds one row.
    expect([...server.rows.keys()]).toEqual([queued.mutation_id]);
    expect(await second.queuedMarksFor("occ-1")).toEqual({});
    expect(disk.stores.mutations.size).toBe(0);
  });
});
