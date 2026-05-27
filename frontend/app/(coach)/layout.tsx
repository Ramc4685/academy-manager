"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";
import { startAutoSync } from "@/lib/offline/sync";
import { CoachInstallCard } from "@/components/coach/install-card";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";

export default function CoachLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("coach");

  useEffect(() => startAutoSync(), []);

  if (!auth.checked) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Loading…</div>;
  }

  if (!auth.authorized) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Redirecting…</div>;
  }

  return (
    <div className="min-h-screen flex flex-col bg-white dark:bg-neutral-950">
      <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-neutral-950/90 backdrop-blur px-4 py-3">
        <div className="flex items-center gap-2">
          <Link href="/coach/dashboard" className="font-semibold">
            Academy
          </Link>
          {!online && (
            <span
              data-testid="offline-indicator"
              className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100"
            >
              Offline
            </span>
          )}
        </div>
        {hasUpdate && (
          <button
            onClick={applyUpdate}
            data-testid="sw-update-button"
            className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700"
          >
            Refresh
          </button>
        )}
      </header>

      <main className="flex-1 px-4 py-4 pb-24">
        <AccessDeniedNotice />
        <CoachInstallCard />
        {children}
      </main>

      <nav className="fixed bottom-0 left-0 right-0 border-t border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-950">
        <div className="mx-auto flex max-w-md">
          <BottomTab
            href="/coach/dashboard"
            label="Home"
            active={pathname === "/coach/dashboard"}
          />
          <BottomTab href="/coach/today" label="Today" active={pathname?.startsWith("/coach/today") ?? false} />
          <BottomTab
            href="/coach/sessions"
            label="Sessions"
            active={pathname?.startsWith("/coach/sessions") ?? false}
          />
          <BottomTab
            href="/coach/profile"
            label="Profile"
            active={pathname?.startsWith("/coach/profile") ?? false}
          />
        </div>
      </nav>
    </div>
  );
}

function BottomTab({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className={`flex flex-1 min-h-touch items-center justify-center text-sm ${
        active ? "text-blue-600 font-semibold" : "text-neutral-600 dark:text-neutral-400"
      }`}
    >
      {label}
    </Link>
  );
}
