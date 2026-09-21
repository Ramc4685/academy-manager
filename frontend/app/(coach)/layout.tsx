"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { COACH_SURFACE_ROLES, canSuperviseCoaching, isAssistantCoach } from "@/lib/api/me";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";
import { startAutoSync } from "@/lib/offline/sync";
import { useNeedsReviewCount } from "@/lib/offline/use-needs-review-count";
import { CoachInstallCard } from "@/components/coach/install-card";
import { CoachSurfaceProvider } from "@/components/coach/coach-surface-context";
import { ToastProvider } from "@/components/ds/toast";
import { PersonaSwitcher } from "@/components/persona/persona-switcher";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";
import { AuthUnavailableScreen } from "@/components/persona/auth-unavailable";
import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { ShellBackButton } from "@/components/persona/back-button";
import { listCoachMessages } from "@/lib/api/v2/messages";
import { queryKeys } from "@/lib/query/keys";

const COACH_TOP_LEVEL_ROUTES = [
  "/coach/today",
  "/coach/sessions",
  "/coach/profile",
  "/coach/calendar",
  "/coach/messages",
  "/coach/needs-review",
] as const;
// Issue #777: the coach's home is the day they teach. /coach/dashboard was a
// second, emptier copy of Today (hardcoded-zero tiles, nothing for a covering
// owner) and was deleted rather than repaired.
const COACH_HOME = "/coach/today";

export default function CoachLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  // Academy admins/owners may open the coach shell to cover any session
  // (#632); assistant coaches get it scoped to the sessions that list them.
  const auth = usePersonaAuth("coach", { alsoAllow: COACH_SURFACE_ROLES });
  const supervising = auth.authorized && canSuperviseCoaching(auth.user.roles);
  const assistant = auth.authorized && isAssistantCoach(auth.user.roles);

  const { data: messagesData } = useQuery({
    queryKey: queryKeys.coach.messages(),
    queryFn: listCoachMessages,
    // Assistants are not a messaging audience: the BFF 404s the inbox for
    // them, so never poll it.
    enabled: auth.authorized && !assistant,
    refetchInterval: 30_000,
  });
  const unreadCount = (messagesData?.messages ?? []).filter((m) => !m.read).length;
  // #841: marks that failed and are waiting in the tray. The entry only
  // appears when there is something to resolve — an always-on "Needs review"
  // link reads as a standing chore on a shell this small.
  const needsReviewCount = useNeedsReviewCount(auth.authorized);

  useEffect(() => startAutoSync(), []);

  if (!auth.checked) {
    return <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>Loading…</div>;
  }

  if (auth.unavailable) {
    return <AuthUnavailableScreen onRetry={auth.retry} />;
  }

  if (!auth.authorized) {
    return <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--rally-paper)" }}>Redirecting…</div>;
  }

  return (
    <ToastProvider>
    <CoachSurfaceProvider
      assistant={assistant}
      userId={auth.authorized ? auth.user.user_id : null}
      supervisor={supervising}
    >
    <div
      className="min-h-screen flex flex-col"
      style={
        {
          background: "var(--rally-paper)",
          "--coach-bottom-nav-height": "72px",
        } as React.CSSProperties
      }
    >
      {/*
        #745: this row must survive its widest combination — an academy admin
        covering a session (back button + persona switcher) whose phone has
        gone offline (Offline chip) with a service-worker update waiting
        (Refresh). On one no-wrap line that overflowed a 390px viewport and
        pushed Log out off-screen, so both clusters wrap (the admin session
        header did the same in #716). The safe-area top padding (#647) stays.
      */}
      <header
        className="sticky top-0 z-10 flex flex-wrap items-center gap-y-2 px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]"
        style={{ background: "#0a0f1c", borderBottom: "1px solid #1e293b" }}
      >
        <div className="flex min-w-0 items-center gap-2">
          <ShellBackButton known={COACH_TOP_LEVEL_ROUTES} home={COACH_HOME} variant="dark" />
          <Link href={COACH_HOME} className="flex min-w-0 items-center gap-2">
            <div
              className="h-7 w-7 shrink-0 rounded-md flex items-center justify-center font-bold text-xs"
              style={{ background: "#facc15", color: "#0a0f1c" }}
            >
              C
            </div>
            <span className="truncate font-semibold text-white text-[15px] tracking-tight">
              Academy
            </span>
          </Link>
        </div>
        <div className="ml-auto flex min-w-0 items-center justify-end gap-2">
          {/*
            #866: Calendar/Messages/Needs review moved to the bottom nav —
            they're thumb-reach destinations, not header decoration, and
            keeping them here is what forced this row to wrap at 400px once
            the Needs review badge appeared.
          */}
          <PersonaSwitcher current="coach" variant="dark" />
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
        {supervising && (
          <p
            data-testid="coach-supervisor-banner"
            className="mb-4 rounded-md border px-3 py-2 text-[13px]"
            style={{
              background: "rgba(250,204,21,0.12)",
              borderColor: "rgba(250,204,21,0.5)",
              color: "var(--rally-ink)",
            }}
          >
            <span className="font-semibold">Admin coverage.</span> You can see every session in
            the academy and mark attendance for any of them. Marks are recorded under your name.
          </p>
        )}
        {assistant && (
          <p
            data-testid="coach-assistant-banner"
            className="mb-4 rounded-md border px-3 py-2 text-[13px]"
            style={{
              background: "rgba(250,204,21,0.12)",
              borderColor: "rgba(250,204,21,0.5)",
              color: "var(--rally-ink)",
            }}
          >
            <span className="font-semibold">Assistant coach.</span> You see the sessions
            you&apos;re assigned to and can mark attendance, update skills and add notes.
          </p>
        )}
        <CoachInstallCard />
        {children}
      </main>

      <nav
        className="fixed bottom-0 left-0 right-0 z-30 pb-[env(safe-area-inset-bottom)]"
        style={{ background: "#0a0f1c", borderTop: "1px solid #1e293b" }}
      >
        <div className="mx-auto flex max-w-md">
          <BottomTab href="/coach/today" label="Today" active={pathname?.startsWith("/coach/today") ?? false} />
          <BottomTab href="/coach/sessions" label="Sessions" active={pathname?.startsWith("/coach/sessions") ?? false} />
          <BottomTab
            href="/coach/calendar"
            label="Calendar"
            active={pathname?.startsWith("/coach/calendar") ?? false}
            testId="nav-calendar"
          />
          {!assistant && (
            <BottomTab
              href="/coach/messages"
              label="Messages"
              active={pathname?.startsWith("/coach/messages") ?? false}
              testId="nav-messages"
              badge={unreadCount > 0 ? { testId: "messages-unread-badge", kind: "dot" } : undefined}
            />
          )}
          {needsReviewCount > 0 && (
            <BottomTab
              href="/coach/needs-review"
              label="Review"
              active={pathname?.startsWith("/coach/needs-review") ?? false}
              testId="nav-needs-review"
              ariaLabel={`Needs review: ${needsReviewCount} ${needsReviewCount === 1 ? "mark" : "marks"}`}
              badge={{ testId: "needs-review-count", kind: "count", count: needsReviewCount }}
            />
          )}
          <BottomTab href="/coach/profile" label="Profile" active={pathname?.startsWith("/coach/profile") ?? false} />
        </div>
      </nav>
    </div>
    </CoachSurfaceProvider>
    </ToastProvider>
  );
}

interface BottomTabBadge {
  testId: string;
  kind: "dot" | "count";
  count?: number;
}

function BottomTab({
  href,
  label,
  active,
  testId,
  ariaLabel,
  badge,
}: {
  href: string;
  label: string;
  active: boolean;
  testId?: string;
  ariaLabel?: string;
  badge?: BottomTabBadge;
}) {
  return (
    <Link
      href={href as Parameters<typeof Link>[0]["href"]}
      data-testid={testId}
      aria-label={ariaLabel}
      className="relative flex min-h-[var(--coach-bottom-nav-height)] flex-1 items-center justify-center text-[13px] font-medium transition-colors"
      style={{
        // rally.subtle-ink (#94a3b8) is the night-surface muted token: 7.5:1 on
        // the #0a0f1c nav, where rally.muted (#64748b) was only 4.0:1 (#844).
        color: active ? "#facc15" : "#94a3b8",
        borderTop: `2px solid ${active ? "#facc15" : "transparent"}`,
      }}
    >
      {label}
      {badge?.kind === "dot" && (
        <span
          data-testid={badge.testId}
          className="absolute top-2 right-[calc(50%-22px)] h-2 w-2 rounded-full"
          style={{ background: "#facc15" }}
        />
      )}
      {badge?.kind === "count" && (
        <span
          data-testid={badge.testId}
          className="absolute top-1.5 right-[calc(50%-26px)] flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[10px] font-bold"
          style={{ background: "#facc15", color: "#0a0f1c" }}
        >
          {badge.count}
        </span>
      )}
    </Link>
  );
}

