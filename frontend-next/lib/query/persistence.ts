"use client";

import { QueryClient } from "@tanstack/react-query";

/**
 * TanStack Query persistence — IndexedDB-backed, scoped to coach.* keys.
 *
 * Wave 1A: persists GET reads for coach (today + roster). Wave 1B adds the
 * mutation queue (separate concern, lib/offline/queue.ts).
 *
 * We intentionally do not persist admin or parent queries — those personas
 * have their own caches added in their waves.
 */
export async function attachPersistence(client: QueryClient): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    const [{ persistQueryClient }, { createSyncStoragePersister }] = await Promise.all([
      import("@tanstack/react-query-persist-client"),
      import("@tanstack/query-sync-storage-persister"),
    ]);

    // The "sync" storage persister wants a synchronous Storage interface.
    // IndexedDB is async, so we adapt with localStorage as the persister
    // backend (small, sync) and let the cache itself live in the
    // QueryClient. Wave 1A's offline-read budget is small enough that
    // localStorage capacity suffices.
    persistQueryClient({
      queryClient: client,
      persister: createSyncStoragePersister({ storage: window.localStorage }) as unknown as Parameters<
        typeof persistQueryClient
      >[0]["persister"],
      buster: "coach-success-only-v1",
      maxAge: 24 * 60 * 60 * 1000,
      dehydrateOptions: {
        shouldDehydrateQuery: (q) =>
          Array.isArray(q.queryKey) &&
          q.queryKey[0] === "coach" &&
          q.state.status === "success",
      },
    });
  } catch (err) {
    // Persistence is a progressive enhancement — failing to attach must
    // never block the app.
    // eslint-disable-next-line no-console
    console.warn("Query persistence unavailable:", err);
  }
}

// IndexedDB-backed persister removed in favor of localStorage; the
// @tanstack/query-sync-storage-persister package needs a sync Storage
// interface and IndexedDB is async. If we outgrow localStorage's quota
// for coach offline reads, switch to @tanstack/query-async-storage-persister
// and bring back an IDB-backed adapter.
