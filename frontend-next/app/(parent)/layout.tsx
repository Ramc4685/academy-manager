"use client";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";

export default function ParentLayout({ children }: { children: React.ReactNode }) {
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("parent");

  if (!auth.checked) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Loading…</div>;
  }

  if (!auth.authorized) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Redirecting…</div>;
  }

  return (
    <div className="min-h-screen bg-white dark:bg-neutral-950">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-neutral-950/90 backdrop-blur px-4 py-3">
        <span className="font-semibold">Academy</span>
        <div className="flex items-center gap-2">
          {!online && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100">
              Offline
            </span>
          )}
          {hasUpdate && (
            <button onClick={applyUpdate} className="min-h-touch rounded-md bg-blue-600 px-3 text-sm text-white">
              Refresh
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-md px-4 py-6">{children}</main>
    </div>
  );
}
