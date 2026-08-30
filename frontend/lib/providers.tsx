"use client";

import { ReactNode, useEffect, useState } from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { handleGlobalMutationError } from "@/lib/query/mutation-errors";
import { attachPersistence } from "@/lib/query/persistence";

/**
 * Root providers wrapper.
 *
 * Wave 1A adds persistence here (TanStack Query persistence plugin) scoped to
 * coach query keys only — so admin/parent state never bleeds into IndexedDB.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        // Global mutation error feedback (#509): any mutation without its own
        // onError surfaces failures via the mounted ToastProvider.
        mutationCache: new MutationCache({
          onError: (error, _variables, _context, mutation) => {
            handleGlobalMutationError(error, mutation);
          },
        }),
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000, // 5 min
            gcTime: 60 * 60 * 1000, // 1 hour
            retry: (failureCount, error: unknown) => {
              // Don't retry 4xx — those are domain errors, not transient.
              if (
                typeof error === "object" &&
                error !== null &&
                "status" in error &&
                typeof (error as { status: number }).status === "number" &&
                (error as { status: number }).status >= 400 &&
                (error as { status: number }).status < 500
              ) {
                return false;
              }
              return failureCount < 3;
            },
            refetchOnWindowFocus: true,
          },
        },
      })
  );

  useEffect(() => {
    void attachPersistence(client);
  }, [client]);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
