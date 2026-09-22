"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getAdminAcademy, getAdminInboxCounts } from "@/lib/api/admin";
import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";
import { queryKeys } from "@/lib/query/keys";
import { TenantProvider } from "@/lib/tenant/tenant-context";
import { useIsDesktop } from "@/lib/use-is-desktop";

import { Avatar } from "@/components/ds/avatar";
import { Icon } from "@/components/ds/icons";
import { ToastProvider } from "@/components/ds/toast";
import { ShuttleMark } from "@/components/ds/shuttle";
import {
  ADMIN_NAV,
  adminTopLevelRoutes,
  isOwnerOnlyRoute,
  metaForPath,
  navForRoles,
  type AdminNavGroup,
  type AdminNavItem,
  type AdminNavIconKey,
} from "@/components/admin/screen-meta";
import { OwnerOnlyPanel, OwnerProvider } from "@/components/admin/owner-context";
import {
  AdminActionSlotOutlet,
  AdminActionSlotProvider,
} from "@/components/admin/admin-action-slot";
import { UnsavedChangesProvider } from "@/components/admin/unsaved-changes-guard";
import { PeopleSearch } from "@/components/admin/PeopleSearch";
import { TenantSwitcher } from "@/components/admin/tenant-switcher";
import { PersonaSwitcher } from "@/components/persona/persona-switcher";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";
import { AuthUnavailableScreen } from "@/components/persona/auth-unavailable";
import { PersonaLogoutButton } from "@/components/persona/logout-button";
import { ShellBackButton } from "@/components/persona/back-button";

const ADMIN_TOP_LEVEL_ROUTES: readonly string[] = adminTopLevelRoutes();
const ADMIN_HOME = "/admin";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/admin";
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("admin");
  const isDesktop = useIsDesktop();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // A persona switch from the drawer navigates; close it so it does not
  // hang open over the new page.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);
  // A tenant switch does NOT navigate (it only dispatches an event and the
  // page refetches in place), so close the drawer on that event too.
  useEffect(() => {
    const handler = () => setDrawerOpen(false);
    window.addEventListener("am:tenant-changed", handler);
    return () => window.removeEventListener("am:tenant-changed", handler);
  }, []);
  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
    enabled: auth.checked && auth.authorized,
  });
  // Issue #842: feed the Inbox nav badge from the same queue-counts endpoint
  // and cache key the Inbox page itself uses (lib/api/admin.ts), so this adds
  // no new polling — React Query dedupes the request across the shell and
  // the page.
  const inboxCountsQuery = useQuery({
    queryKey: queryKeys.admin.inboxCounts(),
    queryFn: getAdminInboxCounts,
    enabled: auth.checked && auth.authorized,
  });

  if (!auth.checked) {
    return (
      <div className="min-h-screen flex items-center justify-center text-neutral-500">
        Loading…
      </div>
    );
  }

  if (auth.unavailable) {
    return <AuthUnavailableScreen onRetry={auth.retry} />;
  }

  if (!auth.authorized) {
    return (
      <div className="min-h-screen flex items-center justify-center text-neutral-500">
        Redirecting…
      </div>
    );
  }

  const meta = metaForPath(pathname);
  const adminName = auth.user?.email ?? "Admin";
  const adminRole = auth.isOwner ? "Owner" : auth.user?.roles.includes("admin") ? "Admin" : "Staff";
  const academyName = displayAcademyName(academyQuery.data?.display_name);
  // Owner-only destinations are dropped from the nav for admins without the
  // scope, and landing on one directly shows the owner-only panel instead of a
  // page whose every request would 404.
  const inboxPending = inboxCountsQuery.data?.total ?? 0;
  const nav = navForRoles(ADMIN_NAV, auth.isOwner).map((group) => ({
    ...group,
    items: group.items.map((item) =>
      item.href === "/admin/inbox"
        ? { ...item, count: inboxPending || undefined }
        : item,
    ),
  }));
  const ownerOnlyHere = isOwnerOnlyRoute(pathname) && !auth.isOwner;

  return (
    <TenantProvider>
      <OwnerProvider isOwner={auth.isOwner}>
      <ToastProvider>
      <TenantChangeInvalidator />
      <AdminActionSlotProvider>
      {/* #893: the unsaved-changes guard wraps the SHELL, not one page, so a
          sidebar/drawer link or a reload asks before it discards a draft. */}
      <UnsavedChangesProvider>
      <div className="min-h-screen flex bg-rally-paper">
        {/* Exactly one sidebar tree is mounted at a time. Both carry the
            account controls (switchers, logout) with the same testids, so
            CSS-hiding the desktop sidebar on phones would leave duplicates
            in the DOM. */}
        {isDesktop ? (
          <DesktopSidebar
            nav={nav}
            pathname={pathname}
            adminName={adminName}
            adminRole={adminRole}
            academyName={academyName}
          />
        ) : (
          drawerOpen && (
            <MobileDrawer
              nav={nav}
              pathname={pathname}
              adminName={adminName}
              adminRole={adminRole}
              academyName={academyName}
              onClose={() => setDrawerOpen(false)}
            />
          )
        )}

        {/* Main column */}
        <div className="flex flex-col flex-1 min-w-0">
          <RallyTopbar
            title={meta.title}
            subtitle={meta.subtitle}
            breadcrumbs={meta.breadcrumbs}
            online={online}
            hasUpdate={hasUpdate}
            onApplyUpdate={applyUpdate}
            onOpenDrawer={() => setDrawerOpen(true)}
          />
          <main className="flex-1 p-4 md:p-6 overflow-y-auto">
            <AccessDeniedNotice />
            {ownerOnlyHere ? <OwnerOnlyPanel /> : children}
          </main>
        </div>
      </div>
      </UnsavedChangesProvider>
      </AdminActionSlotProvider>
      </ToastProvider>
      </OwnerProvider>
    </TenantProvider>
  );
}

function displayAcademyName(name: string | null | undefined): string {
  const trimmed = name?.trim();
  return trimmed || "Academy";
}

/**
 * Listens for `am:tenant-changed` events dispatched by the tenant
 * switcher and invalidates the entire React Query cache. Without this,
 * pages would render stale data from the previous academy until the
 * user navigated.
 */
function TenantChangeInvalidator() {
  const queryClient = useQueryClient();
  useEffect(() => {
    const handler = () => {
      void queryClient.invalidateQueries();
    };
    window.addEventListener("am:tenant-changed", handler);
    return () => window.removeEventListener("am:tenant-changed", handler);
  }, [queryClient]);
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar (desktop)
// ─────────────────────────────────────────────────────────────────────────────

function DesktopSidebar({
  nav,
  pathname,
  adminName,
  adminRole,
  academyName,
}: {
  nav: ReadonlyArray<AdminNavGroup>;
  pathname: string;
  adminName: string;
  adminRole: string;
  academyName: string;
}) {
  return (
    <aside
      className="hidden lg:flex lg:flex-col lg:w-60 lg:shrink-0 lg:h-screen lg:sticky lg:top-0 lg:overflow-hidden"
      style={{
        background: "var(--rally-night)",
        color: "var(--rally-bright)",
        borderRight: "1px solid var(--rally-night-line)",
      }}
      aria-label="Admin navigation"
    >
      <SidebarBrand academyName={academyName} />
      <nav className="flex-1 min-h-0 overflow-y-auto py-2">
        {nav.map((group) => (
          <NavGroup key={group.group} group={group.group} items={group.items} pathname={pathname} />
        ))}
      </nav>
      <SidebarAccountSection name={adminName} role={adminRole} />
    </aside>
  );
}

function SidebarBrand({ academyName, bordered = true }: { academyName: string; bordered?: boolean }) {
  return (
    <div
      className={bordered ? "px-5 py-5 border-b" : "px-5 py-4"}
      style={bordered ? { borderColor: "var(--rally-night-line)" } : undefined}
    >
      <div className="flex items-center gap-2.5">
        <div
          className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-md"
          style={{ background: "var(--rally-ink)", border: "1px solid var(--rally-night-line)" }}
        >
          <span
            className="absolute left-0 right-0"
            style={{ top: "50%", height: 2, background: "var(--rally-volt)", transform: "translateY(-50%)" }}
          />
          <ShuttleMark size={18} />
        </div>
        <div className="leading-tight min-w-0">
          <div className="font-display font-bold text-[15px] text-white tracking-[-0.01em] truncate max-w-[160px]" title={academyName}>
            {academyName}
          </div>
          <div className="font-mono text-[9px] font-bold tracking-lane mt-0.5" style={{ color: "var(--rally-subtle-ink)" }}>
            Academy Manager
          </div>
        </div>
      </div>
    </div>
  );
}

function NavGroup({
  group,
  items,
  pathname,
}: {
  group: string;
  items: ReadonlyArray<AdminNavItem>;
  pathname: string;
}) {
  return (
    // Six groups (sidebar regroup spec §2) means six captions where there were
    // three; the caption chrome is trimmed (pt-1.5, leading-[10px], pb-1) so
    // the whole nav still fits a 1280x900 viewport without scrolling.
    <div className="pt-1.5">
      <div
        className="px-[18px] pb-1 font-mono text-[9px] leading-[10px] font-bold tracking-[0.22em]"
        style={{ color: "var(--rally-subtle-ink)" }}
      >
        {group}
      </div>
      {items.map((item) => (
        <NavRow key={item.href} item={item} active={item.match(pathname)} />
      ))}
    </div>
  );
}

function NavRow({ item, active }: { item: AdminNavItem; active: boolean }) {
  return (
    <Link
      href={item.href as Parameters<typeof Link>[0]["href"]}
      data-testid={`admin-nav-${item.id}`}
      // Issue #842: py-1.5 (was py-[9px]) is part of closing the ~99px fold
      // gap at a 1280x900 viewport once the account block below was
      // compacted — the row still clears the icon's own 16px box plus 13px
      // text, well above the app's smallest existing tap targets.
      //
      // Issue #896: the same component is the phone drawer's row, where 32px
      // is under the 44px touch minimum. `min-h-touch lg:min-h-0` gives the
      // drawer (rendered only below lg) a 44px row while the desktop sidebar
      // (only at lg:) keeps #842's density, with no prop threading.
      className="flex min-h-touch items-center gap-2.5 px-[18px] py-1.5 text-[13px] transition-colors lg:min-h-0 lg:py-[5px]"
      style={{
        background: active ? "var(--rally-night-line)" : "transparent",
        borderLeft: `2px solid ${active ? "var(--rally-volt)" : "transparent"}`,
        color: active ? "#fff" : "var(--rally-subtle-ink)",
        fontWeight: active ? 600 : 500,
      }}
    >
      <span className="flex" style={{ color: active ? "var(--rally-volt)" : "var(--rally-muted)" }}>
        {renderNavIcon(item.icon, 16, "currentColor")}
      </span>
      <span className="flex-1">{item.label}</span>
      {item.count != null && (
        <span
          className="font-mono text-[10px] font-bold tracking-[0.05em] px-1.5 rounded-[3px]"
          style={{
            // #896: the non-urgent fill was an 8%-white overlay. An alpha
            // overlay has no contrast ratio of its own — read literally it is
            // near-white, which is how the critique measured 1.48:1 against
            // the bright text. Both opaque fills below clear AA against
            // --rally-bright (night-line 9.9:1, night 12.9:1), and swapping
            // them by `active` keeps the badge reading as a pill on either
            // row background (an active row is itself night-line).
            background: item.urgent
              ? "var(--rally-volt)"
              : active
                ? "var(--rally-night)"
                : "var(--rally-night-line)",
            color: item.urgent ? "var(--rally-ink)" : "var(--rally-bright)",
            padding: "1px 6px",
          }}
        >
          {item.count}
        </span>
      )}
    </Link>
  );
}

function renderNavIcon(key: AdminNavIconKey, size: number, color: string) {
  const fn = Icon[key];
  if (typeof fn === "function") return fn(size, color);
  return Icon.home(size, color);
}

/**
 * Account-level controls (view switcher, academy switcher, logout) plus the
 * signed-in user row. Lives in the navigation surface on every width so the
 * topbar keeps only the menu, back button, title and one page action.
 *
 * The section sits at the bottom of a scroll container, so both switcher
 * menus are flipped to open upward and stretch to the section's width; a
 * downward, right-anchored menu would be clipped by the aside's overflow.
 *
 * Issue #842: this used to be two separate bordered/padded blocks
 * (switchers+logout, then the user pill). At a 1280x900 viewport their
 * combined footprint pushed COMMS · OPS below the fold. Merging them into one
 * block with a single border and tighter padding gets the whole nav back
 * inside the viewport without shrinking touch targets below `min-h-touch`.
 */
function SidebarAccountSection({ name, role }: { name: string; role: string }) {
  return (
    <div
      className="p-2.5 border-t shrink-0 flex flex-col gap-2 [&_[role=listbox]]:bottom-full [&_[role=listbox]]:top-auto [&_[role=listbox]]:mb-1 [&_[role=listbox]]:mt-0 [&_[role=listbox]]:left-0 [&_[role=listbox]]:right-0 [&_[role=listbox]]:w-auto"
      style={{ borderColor: "var(--rally-night-line)" }}
      data-testid="admin-sidebar-account"
    >
      <PersonaSwitcher current="admin" variant="dark" />
      <TenantSwitcher variant="dark" />
      <PersonaLogoutButton
        className="w-full min-h-touch rounded-md border border-white/20 bg-white/10 px-3 text-[13px] font-semibold text-white hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white/40"
      />
      <div
        className="flex items-center gap-2.5 px-1 pt-2 mt-0.5 border-t"
        style={{ borderColor: "var(--rally-night-line)" }}
        data-testid="admin-sidebar-user"
      >
        <Avatar name={name} size={28} />
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold text-white tracking-[-0.005em] truncate">{name}</div>
          <div
            className="font-mono text-[9px] font-bold tracking-[0.15em] mt-0.5"
            style={{ color: "var(--rally-subtle-ink)" }}
          >
            {role}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Mobile drawer
// ─────────────────────────────────────────────────────────────────────────────

function MobileDrawer({
  nav,
  pathname,
  adminName,
  adminRole,
  academyName,
  onClose,
}: {
  nav: ReadonlyArray<AdminNavGroup>;
  pathname: string;
  adminName: string;
  adminRole: string;
  academyName: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <div
        className="absolute inset-0 bg-black/40"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className="relative z-50 flex flex-col w-64 h-full shadow-xl overflow-hidden pt-[env(safe-area-inset-top,0px)]"
        style={{ background: "var(--rally-night)", color: "var(--rally-bright)" }}
        aria-label="Admin navigation"
        data-testid="admin-mobile-drawer"
      >
        <div className="flex items-center justify-between pr-3 border-b shrink-0" style={{ borderColor: "var(--rally-night-line)" }}>
          <SidebarBrand academyName={academyName} bordered={false} />
          <button
            aria-label="Close menu"
            onClick={onClose}
            className="min-h-touch min-w-touch flex items-center justify-center rounded-md"
            style={{ color: "var(--rally-subtle-ink)" }}
          >
            ✕
          </button>
        </div>
        <nav className="flex-1 min-h-0 overflow-y-auto py-2" onClick={onClose}>
          {nav.map((group) => (
            <NavGroup key={group.group} group={group.group} items={group.items} pathname={pathname} />
          ))}
        </nav>
        {/* Outside the closing <nav>: opening a switcher menu must not close
            the drawer. Navigation from a menu closes it via the pathname
            effect in AdminLayout. */}
        <SidebarAccountSection name={adminName} role={adminRole} />
      </aside>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Topbar
// ─────────────────────────────────────────────────────────────────────────────

interface TopbarProps {
  title: string;
  subtitle: string;
  breadcrumbs: ReadonlyArray<string>;
  online: boolean;
  hasUpdate: boolean;
  onApplyUpdate: () => void;
  onOpenDrawer: () => void;
}

function RallyTopbar({
  title,
  subtitle,
  breadcrumbs,
  online,
  hasUpdate,
  onApplyUpdate,
  onOpenDrawer,
}: TopbarProps) {
  return (
    <header
      className="sticky top-0 z-30 border-b bg-white/95 backdrop-blur px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] md:px-6"
      style={{ borderColor: "var(--rally-line)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <button
            aria-label="Open menu"
            data-testid="admin-open-drawer"
            onClick={onOpenDrawer}
            className="lg:hidden min-h-touch min-w-touch flex items-center justify-center rounded-md text-rally-muted"
          >
            ☰
          </button>
          <ShellBackButton known={ADMIN_TOP_LEVEL_ROUTES} home={ADMIN_HOME} variant="light" />
          <div className="min-w-0">
            {breadcrumbs.length > 0 && (
              <div className="font-mono text-[10px] font-bold tracking-overline uppercase text-rally-muted truncate">
                {breadcrumbs.join(" · ")}
              </div>
            )}
            <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em] text-rally-ink leading-tight">
              {title}
            </h1>
            {subtitle && (
              <p className="text-[13px] text-rally-muted mt-0.5 truncate">{subtitle}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* #865: one search for students, families and staff, at every
              width. It is a dialog, not a route — see PeopleSearch.tsx. */}
          <PeopleSearch />
          <AdminActionSlotOutlet />
          {!online && (
            <span
              data-testid="offline-indicator"
              className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            >
              Offline
            </span>
          )}
          {hasUpdate && (
            <button
              onClick={onApplyUpdate}
              data-testid="sw-update-button"
              className="min-h-touch rounded-md bg-rally-cobalt-600 px-3 text-sm font-medium text-white hover:bg-rally-cobalt-700"
              style={{ background: "var(--rally-cobalt)" }}
            >
              Refresh
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
