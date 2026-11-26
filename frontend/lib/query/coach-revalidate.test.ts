import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { QueryClient, QueryObserver, hydrate } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { applyCoachQueryDefaults, PERSISTER_BUSTER } from "./persistence";

/**
 * Coach rosters change under a coach who still holds a cached copy (new
 * assignment, transfer). A 5-minute staleTime hid that for minutes, so coach
 * reads must paint the persisted copy and revalidate on mount.
 */
describe("coach query defaults", () => {
  it("refetches a persisted coach read on mount while painting the cached copy", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: 5 * 60 * 1000 } } });
    applyCoachQueryDefaults(client);
    const key = ["coach", "today", "2026-11-28"];
    // Simulate the persister restoring a copy written a moment ago.
    hydrate(client, {
      mutations: [],
      queries: [
        {
          queryKey: key,
          queryHash: JSON.stringify(key),
          state: {
            data: { sessions: ["Dev Patel"] },
            dataUpdateCount: 1,
            dataUpdatedAt: Date.now(),
            error: null,
            errorUpdateCount: 0,
            errorUpdatedAt: 0,
            fetchFailureCount: 0,
            fetchFailureReason: null,
            fetchMeta: null,
            isInvalidated: false,
            status: "success",
            fetchStatus: "idle",
          },
        },
      ],
    });
    const queryFn = vi.fn().mockResolvedValue({ sessions: [] });
    const observer = new QueryObserver(client, { queryKey: key, queryFn });
    const seen: unknown[] = [];
    const unsubscribe = observer.subscribe((r) => seen.push(r.data));
    expect(observer.getCurrentResult().data).toEqual({ sessions: ["Dev Patel"] });
    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual({ sessions: [] }));
    unsubscribe();
  });

  it("leaves other personas on the global staleTime", () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: 5 * 60 * 1000 } } });
    applyCoachQueryDefaults(client);
    expect(client.defaultQueryOptions({ queryKey: ["parent", "children"] }).staleTime).toBe(5 * 60 * 1000);
    expect(client.defaultQueryOptions({ queryKey: ["coach", "schedule"] }).staleTime).toBe(0);
  });

  it("busts copies persisted under the old 5-minute policy", () => {
    expect(PERSISTER_BUSTER).not.toBe("coach-success-only-v1");
  });
});

const FRONTEND = path.resolve(__dirname, "../..");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name))
    .map((e) => path.join(e.parentPath, e.name));
}

describe("coach code sets no per-query staleTime", () => {
  it.each(["app/(coach)", "components/coach"])("%s", (dir) => {
    const offenders = sources(path.join(FRONTEND, dir)).filter((f) =>
      /staleTime\s*:/.test(readFileSync(f, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});
