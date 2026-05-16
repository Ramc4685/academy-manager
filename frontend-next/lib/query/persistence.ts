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
    const [{ persistQueryClient }, { createAsyncStoragePersister }] = await Promise.all([
      import("@tanstack/react-query-persist-client"),
      import("@tanstack/query-sync-storage-persister"),
    ]);

    const idb = createIndexedDBPersister();

    persistQueryClient({
      queryClient: client,
      persister: createAsyncStoragePersister({ storage: idb }) as unknown as Parameters<
        typeof persistQueryClient
      >[0]["persister"],
      maxAge: 24 * 60 * 60 * 1000,
      dehydrateOptions: {
        shouldDehydrateQuery: (q) => Array.isArray(q.queryKey) && q.queryKey[0] === "coach",
      },
    });
  } catch (err) {
    // Persistence is a progressive enhancement — failing to attach must
    // never block the app.
    // eslint-disable-next-line no-console
    console.warn("Query persistence unavailable:", err);
  }
}

/** Minimal IndexedDB storage shim with the async-storage shape. */
function createIndexedDBPersister() {
  const DB_NAME = "rq-coach";
  const STORE = "queries";

  function open(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest): Promise<T> {
    const db = await open();
    return new Promise<T>((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const r = run(t.objectStore(STORE));
      r.onsuccess = () => resolve(r.result as T);
      r.onerror = () => reject(r.error);
    });
  }
  return {
    getItem: (k: string) => tx<string | null>("readonly", (s) => s.get(k)),
    setItem: (k: string, v: string) => tx<IDBValidKey>("readwrite", (s) => s.put(v, k)),
    removeItem: (k: string) => tx<undefined>("readwrite", (s) => s.delete(k)),
  };
}
