"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";
import { PersonaSwitcher } from "@/components/persona/persona-switcher";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";
import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { ToastProvider } from "@/components/ds/toast";
import { queryKeys } from "@/lib/query/keys";
import { getParentProfile } from "@/lib/api/parent";

// Session-scoped dismissal (issue #380): the banner returns on the next
// login rather than being permanently dismissible — nothing here blocks the
// parent from using the app, it's a nudge, not a gate.
const DISMISS_KEY = "am.parent.profileBannerDismissed";

export default function ParentLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("parent");

  if (!auth.checked) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 rounded-xl shimmer" />
          <div className="h-3 w-20 rounded shimmer" />
        </div>
      </div>
    );
  }

  if (!auth.authorized) {
    return <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>Redirecting…</div>;
  }

  return (
    <ToastProvider>
    <div className="min-h-screen flex flex-col pb-20" style={{ background: "var(--rally-paper)" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-10 flex items-center justify-between px-4 py-3"
        style={{
          background: "linear-gradient(135deg, #0a0f1c 0%, #0f1d38 100%)",
          borderBottom: "1px solid rgba(250,204,21,0.12)",
        }}
      >
        <Link href="/parent/dashboard" className="flex items-center gap-2.5">
          <div
            className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm shadow-lg"
            style={{ background: "linear-gradient(135deg, #facc15 0%, #f59e0b 100%)", color: "#0a0f1c" }}
          >
            A
          </div>
          <span className="font-semibold text-white text-[15px] tracking-tight">Academy</span>
        </Link>
        <div className="flex items-center gap-2">
          <PersonaSwitcher current="parent" variant="dark" />
          {!online && (
            <span className="rounded-full px-2.5 py-0.5 text-xs font-medium text-amber-300 border border-amber-400/30" style={{ background: "rgba(251,191,36,0.1)" }}>
              Offline
            </span>
          )}
          {hasUpdate && (
            <button
              onClick={applyUpdate}
              className="min-h-touch rounded-lg px-3 text-sm font-semibold text-white transition-all duration-150 active:scale-95"
              style={{ background: "var(--rally-cobalt)" }}
            >
              Refresh
            </button>
          )}
          <PersonaLogoutButton
            className="min-h-touch min-w-touch rounded-lg p-2 text-slate-400 hover:bg-white/10"
            labelClassName="sr-only"
          />
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto w-full max-w-md px-4 py-5 animate-fade-in">
        <AccessDeniedNotice />
        <ProfileGapBanner pathname={pathname} />
        {children}
      </main>

      {/* Bottom nav */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-20"
        style={{
          background: "linear-gradient(0deg, #07101f 0%, #0a0f1c 100%)",
          borderTop: "1px solid rgba(255,255,255,0.07)",
        }}
      >
        <div className="mx-auto flex max-w-md">
          <BottomTab href="/parent/dashboard" label="Home" active={pathname === "/parent/dashboard"} icon={<HomeIcon />} />
          <BottomTab href="/parent/children" label="Children" active={pathname?.startsWith("/parent/children") ?? false} icon={<ChildrenIcon />} />
          <BottomTab href="/parent/payments" label="Payments" active={pathname?.startsWith("/parent/payments") ?? false} icon={<PaymentsIcon />} />
          <BottomTab href="/parent/progress" label="Progress" active={pathname?.startsWith("/parent/progress") ?? false} icon={<ProgressIcon />} />
        </div>
      </nav>
    </div>
    </ToastProvider>
  );
}

function BottomTab({
  href,
  label,
  active,
  icon,
}: {
  href: string;
  label: string;
  active: boolean;
  icon: React.ReactNode;
}) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      className="relative flex flex-1 min-h-touch flex-col items-center justify-center gap-0.5 transition-all duration-200"
      style={{ color: active ? "#facc15" : "#475569" }}
    >
      {active && (
        <span
          className="absolute top-0 left-1/2 -translate-x-1/2 h-0.5 w-8 rounded-full"
          style={{ background: "linear-gradient(90deg, #facc15, #f59e0b)" }}
        />
      )}
      <span
        className="transition-transform duration-200"
        style={{ transform: active ? "scale(1.15)" : "scale(1)" }}
      >
        {icon}
      </span>
      <span className="text-[10px] font-semibold tracking-wide">{label}</span>
    </Link>
  );
}

function HomeIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  );
}

function ChildrenIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function PaymentsIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  );
}

function ProgressIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function ProfileGapBanner({ pathname }: { pathname: string | null }) {
  const { data } = useQuery({
    queryKey: queryKeys.parent.profile(),
    queryFn: getParentProfile,
    // This runs in the layout, so it mounts on every parent page. Cache it
    // for the session-ish window the banner cares about rather than
    // refetching on each tab change, and don't retry: the banner is a nudge,
    // so a failed fetch should cost one request and then render nothing.
    staleTime: 5 * 60_000,
    retry: false,
  });
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(typeof window !== "undefined" && window.sessionStorage.getItem(DISMISS_KEY) === "1");
  }, []);

  if (pathname === "/parent/profile") return null;
  if (!data || data.gaps.is_complete || dismissed) return null;

  const childCount = Object.values(data.gaps.children).filter((gaps) => gaps.length > 0).length;
  const total = data.gaps.parent.length + childCount;
  const subject =
    childCount > 0 && data.gaps.parent.length > 0
      ? "your profile and a child's"
      : childCount > 0
        ? "a child's profile"
        : "your profile";

  return (
    <div
      className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 animate-fade-in-up"
      role="status"
    >
      <p className="text-sm text-amber-900">
        {total} detail{total === 1 ? "" : "s"} missing from {subject}.
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <Link
          href="/parent/profile"
          className="rounded-lg bg-amber-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-amber-700"
        >
          Add now
        </Link>
        <button
          type="button"
          aria-label="Dismiss"
          className="rounded-lg px-1.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100"
          onClick={() => {
            window.sessionStorage.setItem(DISMISS_KEY, "1");
            setDismissed(true);
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
