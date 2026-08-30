"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
import { usePersonaAuth } from "@/lib/auth/use-persona-auth";
import { useOnline } from "@/lib/pwa/online";
import { useServiceWorkerUpdate } from "@/lib/pwa/update-flow";
import { queryKeys } from "@/lib/query/keys";
import { TenantProvider } from "@/lib/tenant/tenant-context";

import { Avatar } from "@/components/ds/avatar";
import { Icon } from "@/components/ds/icons";
import { ToastProvider } from "@/components/ds/toast";
import { ShuttleMark } from "@/components/ds/shuttle";
import {
  ADMIN_NAV,
  metaForPath,
  type AdminNavItem,
  type AdminNavIconKey,
} from "@/components/admin/screen-meta";
import {
  AdminActionSlotOutlet,
  AdminActionSlotProvider,
} from "@/components/admin/admin-action-slot";
import { TenantSwitcher } from "@/components/admin/tenant-switcher";
import { PersonaSwitcher } from "@/components/persona/persona-switcher";
import { AccessDeniedNotice } from "@/components/persona/access-denied-notice";
import { AuthUnavailableScreen } from "@/components/persona/auth-unavailable";
import { PersonaLogoutButton } from "@/components/persona/logout-button";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/admin";
  const online = useOnline();
  const { hasUpdate, applyUpdate } = useServiceWorkerUpdate();
  const auth = usePersonaAuth("admin");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
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
  const adminRole = auth.user?.roles.includes("admin") ? "Admin" : "Staff";
  const academyName = displayAcademyName(academyQuery.data?.display_name);

  return (
    <TenantProvider>
      <ToastProvider>
      <TenantChangeInvalidator />
      <AdminActionSlotProvider>
      <div className="min-h-screen flex bg-rally-paper">
        {/* Sidebar — desktop only */}
        <DesktopSidebar
          pathname={pathname}
          adminName={adminName}
          adminRole={adminRole}
          academyName={academyName}
        />

        {/* Mobile drawer */}
        {drawerOpen && (
          <MobileDrawer
            pathname={pathname}
            adminName={adminName}
            adminRole={adminRole}
            academyName={academyName}
            onClose={() => setDrawerOpen(false)}
          />
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
            {children}
          </main>
        </div>
      </div>
      </AdminActionSlotProvider>
      </ToastProvider>
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
  pathname,
  adminName,
  adminRole,
  academyName,
}: {
  pathname: string;
  adminName: string;
  adminRole: string;
  academyName: string;
}) {
  return (
    <aside
      className="hidden lg:flex lg:flex-col lg:w-60 lg:shrink-0 lg:h-screen lg:sticky lg:top-0 lg:overflow-y-auto"
      style={{
        background: "var(--rally-night)",
        color: "var(--rally-bright)",
        borderRight: "1px solid var(--rally-night-line)",
      }}
      aria-label="Admin navigation"
    >
      <SidebarBrand academyName={academyName} />
      <nav className="flex-1 py-2">
        {ADMIN_NAV.map((group) => (
          <NavGroup key={group.group} group={group.group} items={group.items} pathname={pathname} />
        ))}
      </nav>
      <SidebarUserPill name={adminName} role={adminRole} />
    </aside>
  );
}

function SidebarBrand({ academyName }: { academyName: string }) {
  return (
    <div className="px-5 py-5 border-b" style={{ borderColor: "var(--rally-night-line)" }}>
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
    <div className="pt-3.5 pb-1">
      <div
        className="px-[18px] pb-2 font-mono text-[9px] font-bold tracking-[0.22em]"
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
      data-testid={`admin-nav-${slug(item.label)}`}
      className="flex items-center gap-2.5 px-[18px] py-[9px] text-[13px] transition-colors"
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
            background: item.urgent ? "var(--rally-volt)" : "rgba(255,255,255,0.08)",
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

function slug(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function SidebarUserPill({ name, role }: { name: string; role: string }) {
  return (
    <div className="p-3.5 border-t" style={{ borderColor: "var(--rally-night-line)" }}>
      <div
        className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg"
        style={{ background: "var(--rally-night-panel)" }}
      >
        <Avatar name={name} size={32} />
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
  pathname,
  adminName,
  adminRole,
  academyName,
  onClose,
}: {
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
        className="relative z-50 flex flex-col w-64 h-full shadow-xl overflow-y-auto"
        style={{ background: "var(--rally-night)", color: "var(--rally-bright)" }}
        aria-label="Admin navigation"
        data-testid="admin-mobile-drawer"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "var(--rally-night-line)" }}>
          <SidebarBrand academyName={academyName} />
          <button
            aria-label="Close menu"
            onClick={onClose}
            className="min-h-touch min-w-touch flex items-center justify-center rounded-md"
            style={{ color: "var(--rally-subtle-ink)" }}
          >
            ✕
          </button>
        </div>
        <nav className="flex-1 py-2" onClick={onClose}>
          {ADMIN_NAV.map((group) => (
            <NavGroup key={group.group} group={group.group} items={group.items} pathname={pathname} />
          ))}
        </nav>
        <SidebarUserPill name={adminName} role={adminRole} />
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
      className="sticky top-0 z-30 border-b bg-white/95 backdrop-blur px-4 py-3 md:px-6"
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
          <PersonaSwitcher current="admin" />
          <TenantSwitcher />
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
          <PersonaLogoutButton
            className="min-h-touch rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-600 hover:bg-slate-50"
            labelClassName="hidden sm:inline"
          />
        </div>
      </div>
    </header>
  );
}
