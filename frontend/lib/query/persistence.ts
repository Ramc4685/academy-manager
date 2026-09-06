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
/**
 * localStorage key used by createSyncStoragePersister below (its default).
 * Exported so logout can drop the persisted cache — signing out must not
 * leave the previous user's coach reads readable by the next one.
 */
export const PERSISTED_QUERY_CACHE_KEY = "REACT_QUERY_OFFLINE_CACHE";

/** Drop the persisted query cache. Safe to call when nothing is persisted. */
export function clearPersistedQueryCache(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(PERSISTED_QUERY_CACHE_KEY);
  } catch {
    // localStorage can throw in private/blocked contexts — clearing is
    // best-effort and must never block logout.
  }
}

/**
 * Which queries may be written to localStorage.
 *
 * Exported so the exclusion below is guarded by a test rather than only a
 * comment — it is a privacy boundary, and the `messages` check is
 * positional, so a future key shape could otherwise silently start
 * persisting message bodies.
 */
export function shouldPersistQuery(queryKey: unknown, status: string): boolean {
  if (!Array.isArray(queryKey)) return false;
  // coach.* reads are persisted so the PWA works offline — but NOT
  // coach.messages: message bodies are private admin<->coach
  // correspondence, and this persister writes plaintext to localStorage
  // with a 24h maxAge. On a shared club tablet that would outlive the
  // session and be restored for whoever logs in next. Inbox reads are
  // online-only by design (UIM13).
  if (queryKey[0] !== "coach") return false;
  if (queryKey[1] === "messages") return false;
  // Student pricing is not offline-critical; keep proration/pricing out
  // of localStorage so shared coach devices do not retain it.
  if (queryKey[1] === "billing-enrollments") return false;
  // Coach notes about children default to PRIVATE (slice 3) and are
  // online-only reads; their bodies must not sit in localStorage for 24h
  // on a shared device any more than message bodies may.
  if (queryKey[1] === "progress-notes") return false;
  if (queryKey[1] === "skill-notes") return false;
  return status === "success";
}

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
        shouldDehydrateQuery: (q) => shouldPersistQuery(q.queryKey, q.state.status),
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
