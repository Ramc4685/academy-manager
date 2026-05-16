"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";

import { onAuthChange } from "@/lib/auth/firebase";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";

const NAV_ITEMS = [
  { href: "/admin", label: "Dashboard", match: (p: string) => p === "/admin" },
  { href: "/admin/sessions", label: "Sessions", match: (p: string) => p.startsWith("/admin/sessions") },
  { href: "/admin/billing", label: "Billing", match: (p: string) => p.startsWith("/admin/billing") },
  { href: "/admin/finance", label: "Finance", match: (p: string) => p.startsWith("/admin/finance") },
  { href: "/admin/comms", label: "Comms", match: (p: string) => p.startsWith("/admin/comms") },
] as const;

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const [authChecked, setAuthChecked] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(
    () =>
      onAuthChange((user) => {
        if (!user) router.replace("/login");
        setAuthChecked(true);
      }),
    [router]
  );

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center text-neutral-500">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-neutral-50 dark:bg-neutral-950">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar — visible on lg+, hidden on mobile                          */}
      {/* ------------------------------------------------------------------ */}
      <aside className="hidden lg:flex lg:flex-col lg:w-56 lg:shrink-0 lg:border-r lg:border-neutral-200 lg:dark:border-neutral-800 lg:bg-white lg:dark:bg-neutral-950">
        <div className="px-5 py-5 border-b border-neutral-200 dark:border-neutral-800">
          <span className="font-semibold text-lg">Academy Admin</span>
        </div>
        <nav className="flex-1 overflow-y-auto py-4 px-2" aria-label="Admin navigation">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <li key={item.href}>
                <SidebarLink
                  href={item.href}
                  label={item.label}
                  active={item.match(pathname ?? "")}
                />
              </li>
            ))}
          </ul>
        </nav>
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 text-xs text-neutral-400">
          {!online && (
            <span
              data-testid="offline-indicator"
              className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100"
            >
              Offline
            </span>
          )}
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Mobile drawer overlay                                               */}
      {/* ------------------------------------------------------------------ */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40"
            aria-hidden="true"
            onClick={() => setDrawerOpen(false)}
          />
          {/* Drawer panel */}
          <aside className="relative z-50 flex flex-col w-64 h-full bg-white dark:bg-neutral-950 shadow-xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-200 dark:border-neutral-800">
              <span className="font-semibold">Academy Admin</span>
              <button
                aria-label="Close menu"
                onClick={() => setDrawerOpen(false)}
                className="min-h-touch min-w-touch flex items-center justify-center rounded-md text-neutral-500"
              >
                ✕
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto py-4 px-2" aria-label="Admin navigation mobile">
              <ul className="space-y-1">
                {NAV_ITEMS.map((item) => (
                  <li key={item.href}>
                    <SidebarLink
                      href={item.href}
                      label={item.label}
                      active={item.match(pathname ?? "")}
                      onClick={() => setDrawerOpen(false)}
                    />
                  </li>
                ))}
              </ul>
            </nav>
          </aside>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Main content column                                                 */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-neutral-200 dark:border-neutral-800 bg-white/90 dark:bg-neutral-950/90 backdrop-blur px-4 py-3">
          <div className="flex items-center gap-3">
            {/* Hamburger — mobile only */}
            <button
              aria-label="Open menu"
              onClick={() => setDrawerOpen(true)}
              className="lg:hidden min-h-touch min-w-touch flex items-center justify-center rounded-md text-neutral-500"
            >
              ☰
            </button>
            <span className="font-semibold lg:hidden">Admin</span>
          </div>
          <div className="flex items-center gap-2">
            {!online && (
              <span
                data-testid="offline-indicator"
                className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-100"
              >
                Offline
              </span>
            )}
            {hasUpdate && (
              <button
                onClick={applyUpdate}
                data-testid="sw-update-button"
                className="min-h-touch rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700"
              >
                Refresh
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 p-4 md:p-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

function SidebarLink({
  href,
  label,
  active,
  onClick,
}: {
  href: string;
  label: string;
  active: boolean;
  onClick?: () => void;
}) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      onClick={onClick}
      className={`flex items-center min-h-touch rounded-md px-3 text-sm font-medium transition-colors ${
        active
          ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
          : "text-neutral-700 hover:bg-neutral-100 dark:text-neutral-300 dark:hover:bg-neutral-800"
      }`}
    >
      {label}
    </Link>
  );
}
