"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ToastProvider } from "@/components/ds/toast";
import { AuthUnavailableScreen } from "@/components/persona/auth-unavailable";
import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { usePlatformAuth } from "@/lib/auth/use-persona-auth";

/**
 * Platform-operator shell.
 *
 * Guarded on `platform_roles`, which the backend keeps out of the tenant
 * `roles` list — a tenant admin can never reach this surface. Client-side
 * gating is cosmetic only: every `/platform/*` route independently 404s for
 * non-platform callers.
 */
export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const auth = usePlatformAuth();

  if (!auth.checked) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--rally-paper)" }}
      >
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 rounded-xl shimmer" />
          <div className="h-3 w-20 rounded shimmer" />
        </div>
      </div>
    );
  }

  if (auth.unavailable) {
    return <AuthUnavailableScreen onRetry={auth.retry} />;
  }

  if (!auth.authorized) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--rally-paper)" }}
      >
        Redirecting…
      </div>
    );
  }

  return (
    <ToastProvider>
      <div className="min-h-screen flex flex-col" style={{ background: "var(--rally-paper)" }}>
        <header
          className="sticky top-0 z-10 flex items-center justify-between px-4 py-3"
          style={{
            background: "linear-gradient(135deg, #0a0f1c 0%, #0f1d38 100%)",
            borderBottom: "1px solid rgba(250,204,21,0.12)",
          }}
        >
          <div className="flex items-center gap-4">
            <Link href="/platform/tenants" className="flex items-center gap-2.5">
              <div
                className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm shadow-lg"
                style={{
                  background: "linear-gradient(135deg, #facc15 0%, #f59e0b 100%)",
                  color: "#0a0f1c",
                }}
              >
                P
              </div>
              <span className="font-semibold text-white text-[15px] tracking-tight">Platform</span>
            </Link>
            <nav aria-label="Platform sections" className="flex items-center gap-1">
              <PlatformTab
                href="/platform/tenants"
                label="Tenants"
                active={pathname?.startsWith("/platform/tenants") ?? false}
              />
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <span
              data-testid="platform-role-badge"
              className="rounded-full px-2.5 py-0.5 text-xs font-medium text-amber-300 border border-amber-400/30"
              style={{ background: "rgba(251,191,36,0.1)" }}
            >
              {auth.isAdmin ? "Platform admin" : "Support (read-only)"}
            </span>
            <PersonaLogoutButton
              className="min-h-touch min-w-touch rounded-lg p-2 text-slate-400 hover:bg-white/10"
              labelClassName="sr-only"
            />
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl px-4 py-6 animate-fade-in">{children}</main>
      </div>
    </ToastProvider>
  );
}

function PlatformTab({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      aria-current={active ? "page" : undefined}
      className="rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors"
      style={{
        color: active ? "#facc15" : "#94a3b8",
        background: active ? "rgba(250,204,21,0.1)" : "transparent",
      }}
    >
      {label}
    </Link>
  );
}
