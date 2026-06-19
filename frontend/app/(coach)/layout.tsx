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
import { PersonaLogoutButton } from "@/components/persona/logout-button";

export default function CoachLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("coach");

  useEffect(() => startAutoSync(), []);

  if (!auth.checked) {
    return <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>Loading…</div>;
  }

  if (!auth.authorized) {
    return <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>Redirecting…</div>;
  }

  return (
    <div
      className="min-h-screen flex flex-col"
      style={
        {
          background: "var(--rally-paper)",
          "--coach-bottom-nav-height": "72px",
        } as React.CSSProperties
      }
    >
      <header
        className="sticky top-0 z-10 flex items-center justify-between px-4 py-3"
        style={{ background: "#0a0f1c", borderBottom: "1px solid #1e293b" }}
      >
        <Link href="/coach/dashboard" className="flex items-center gap-2">
          <div
            className="h-7 w-7 rounded-md flex items-center justify-center font-bold text-xs"
            style={{ background: "#facc15", color: "#0a0f1c" }}
          >
            C
          </div>
          <span className="font-semibold text-white text-[15px] tracking-tight">Academy</span>
        </Link>
        <div className="flex items-center gap-2">
          {!online && (
            <span className="rounded-full px-2 py-0.5 text-xs font-medium text-amber-300" style={{ background: "rgba(251,191,36,0.15)" }}>
              Offline
            </span>
          )}
          {hasUpdate && (
            <button onClick={applyUpdate} data-testid="sw-update-button" className="min-h-touch rounded-md px-3 text-sm font-medium text-white" style={{ background: "var(--rally-cobalt)" }}>
              Refresh
            </button>
          )}
          <PersonaLogoutButton
            className="min-h-touch min-w-touch rounded-md p-2 text-slate-300 hover:bg-white/10"
            labelClassName="sr-only"
          />
        </div>
      </header>

      <main className="mx-auto w-full max-w-md flex-1 px-4 py-4 pb-[calc(var(--coach-bottom-nav-height)+max(2rem,env(safe-area-inset-bottom)))]">
        <AccessDeniedNotice />
        <CoachInstallCard />
        {children}
      </main>

      <nav
        className="fixed bottom-0 left-0 right-0 z-30 pb-[env(safe-area-inset-bottom)]"
        style={{ background: "#0a0f1c", borderTop: "1px solid #1e293b" }}
      >
        <div className="mx-auto flex max-w-md">
          <BottomTab href="/coach/dashboard" label="Home" active={pathname === "/coach/dashboard"} />
          <BottomTab href="/coach/today" label="Today" active={pathname?.startsWith("/coach/today") ?? false} />
          <BottomTab href="/coach/sessions" label="Sessions" active={pathname?.startsWith("/coach/sessions") ?? false} />
          <BottomTab href="/coach/profile" label="Profile" active={pathname?.startsWith("/coach/profile") ?? false} />
        </div>
      </nav>
    </div>
  );
}

function BottomTab({ href, label, active }: { href: string; label: string; active: boolean }) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="flex min-h-[var(--coach-bottom-nav-height)] flex-1 items-center justify-center text-sm font-medium transition-colors"
      style={{
        color: active ? "#facc15" : "#64748b",
        borderTop: `2px solid ${active ? "#facc15" : "transparent"}`,
      }}
    >
      {label}
    </Link>
  );
}
