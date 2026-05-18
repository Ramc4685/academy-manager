"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";

export default function ParentLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
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
    <div className="min-h-screen bg-white pb-20 dark:bg-neutral-950">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-neutral-950/90 backdrop-blur px-4 py-3">
        <Link href="/parent/dashboard" className="font-semibold">
          Academy
        </Link>
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
      <nav className="fixed bottom-0 left-0 right-0 border-t border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-950">
        <div className="mx-auto flex max-w-md">
          <BottomTab href="/parent/dashboard" label="Home" active={pathname === "/parent/dashboard"} />
          <BottomTab href="/parent/children" label="Children" active={pathname?.startsWith("/parent/children") ?? false} />
          <BottomTab href="/parent/payments" label="Payments" active={pathname?.startsWith("/parent/payments") ?? false} />
          <BottomTab href="/parent/progress" label="Progress" active={pathname?.startsWith("/parent/progress") ?? false} />
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
        active ? "font-semibold text-blue-600" : "text-neutral-600 dark:text-neutral-400"
      }`}
    >
      {label}
    </Link>
  );
}
