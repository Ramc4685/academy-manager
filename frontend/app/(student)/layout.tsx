"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { PersonaSwitcher } from "@/components/persona/persona-switcher";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";
import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { ToastProvider } from "@/components/ds/toast";

export default function StudentLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const auth = usePersonaAuth("student");

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
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>
        Redirecting…
      </div>
    );
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
          <Link href="/student/dashboard" className="flex items-center gap-2.5">
            <div
              className="h-8 w-8 rounded-lg flex items-center justify-center font-bold text-sm shadow-lg"
              style={{ background: "linear-gradient(135deg, #facc15 0%, #f59e0b 100%)", color: "#0a0f1c" }}
            >
              A
            </div>
            <span className="font-semibold text-white text-[15px] tracking-tight">Academy</span>
          </Link>
          <div className="flex items-center gap-2">
            <PersonaSwitcher current="student" variant="dark" />
            <PersonaLogoutButton
              className="min-h-touch min-w-touch rounded-lg p-2 text-slate-400 hover:bg-white/10"
              labelClassName="sr-only"
            />
          </div>
        </header>

        {/* Content */}
        <main className="mx-auto w-full max-w-md px-4 py-5 animate-fade-in">
          <AccessDeniedNotice />
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
            <BottomTab href="/student/dashboard" label="Home" active={pathname === "/student/dashboard"} icon={<HomeIcon />} />
            <BottomTab href="/student/schedule" label="Schedule" active={pathname?.startsWith("/student/schedule") ?? false} icon={<ScheduleIcon />} />
            <BottomTab href="/student/progress" label="Progress" active={pathname?.startsWith("/student/progress") ?? false} icon={<ProgressIcon />} />
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
      <span className="transition-transform duration-200" style={{ transform: active ? "scale(1.15)" : "scale(1)" }}>
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

function ScheduleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
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
