/**
 * Rally admin navigation + per-route topbar metadata.
 *
 * Subtitles are static — the shell does NOT fetch data. Pages that
 * want to surface live counts in the topbar should use AdminActionSlot
 * or render their own header inside the page body.
 */

export type AdminNavIconKey =
  | "home" | "calendar" | "user" | "list" | "check"
  | "pay" | "card" | "bell" | "whistle" | "chart"
  | "msg" | "cog" | "trophy" | "signal" | "filter";

export interface AdminNavItem {
  /** Route URL. */
  href: string;
  /** Label shown in sidebar. */
  label: string;
  /** Icon key resolved against the Rally Icon set. */
  icon: AdminNavIconKey;
  /** Optional count badge. */
  count?: number;
  /** Highlight the badge with volt-yellow if true. */
  urgent?: boolean;
  /** True if pathname `p` should highlight this item. */
  match: (p: string) => boolean;
  /**
   * Money-governance destination: rendered only for academy owners. The
   * backend 404s the underlying routes for admin-only users, so the nav must
   * not advertise them (`navForRoles`).
   */
  ownerOnly?: true;
}

export interface AdminNavGroup {
  /** Mono uppercase label. */
  group: string;
  items: ReadonlyArray<AdminNavItem>;
}

const startsWith = (prefix: string) => (p: string) => p.startsWith(prefix);
const eq = (route: string) => (p: string) => p === route;

/**
 * Rally admin nav, grouped per `assets/admin-screens.jsx:10-30`.
 * Existing admin routes (users, audit-logs, pause-requests, coach-payslip,
 * finance) are preserved as part of the group they fit in.
 */
export const ADMIN_NAV: ReadonlyArray<AdminNavGroup> = [
  {
    group: "WORK",
    items: [
      { href: "/admin", label: "Dashboard", icon: "home", match: eq("/admin") },
      { href: "/admin/sessions", label: "Sessions", icon: "calendar", match: startsWith("/admin/sessions") },
      { href: "/admin/students", label: "Students", icon: "user", match: startsWith("/admin/students") },
      { href: "/admin/pathway", label: "Pathway", icon: "trophy", match: startsWith("/admin/pathway") },
      { href: "/admin/users", label: "Users", icon: "user", match: startsWith("/admin/users") },
      { href: "/admin/registrations", label: "Admissions", icon: "check", match: startsWith("/admin/registrations") },
      { href: "/admin/requests", label: "Requests", icon: "check", match: startsWith("/admin/requests") },
    ],
  },
  {
    group: "MONEY",
    items: [
      {
        href: "/admin/payments",
        label: "Payments",
        icon: "pay",
        match: startsWith("/admin/payments"),
      },
      { href: "/admin/billing-health", label: "Billing Health", icon: "signal", match: startsWith("/admin/billing-health") },
      { href: "/admin/billing-setup", label: "Billing Setup", icon: "user", match: startsWith("/admin/billing-setup") },
      {
        href: "/admin/expenses",
        label: "Expenses",
        icon: "card",
        match: startsWith("/admin/expenses"),
      },
      { href: "/admin/payouts", label: "Coach payouts", icon: "whistle", match: startsWith("/admin/payouts"), ownerOnly: true },
      { href: "/admin/reports", label: "Reports", icon: "chart", match: startsWith("/admin/reports"), ownerOnly: true },
    ],
  },
  {
    group: "COMMS · OPS",
    items: [
      { href: "/admin/messages", label: "Messages", icon: "msg", match: startsWith("/admin/messages") },
      { href: "/admin/waivers", label: "Waivers", icon: "check", match: startsWith("/admin/waivers") },
      { href: "/admin/settings", label: "Settings", icon: "cog", match: startsWith("/admin/settings") },
      { href: "/admin/audit-logs", label: "Audit logs", icon: "filter", match: startsWith("/admin/audit-logs"), ownerOnly: true },
    ],
  },
];

/**
 * Every nav `href` plus the `/admin/dashboard` alias — the routes the shell
 * back button treats as top-level (it renders nothing on them).
 */
export function adminTopLevelRoutes(): string[] {
  return [...ADMIN_NAV.flatMap((group) => group.items.map((item) => item.href)), "/admin/dashboard"];
}

/**
 * Nav as seen by the current user: owner-only items are removed for admins
 * without the owner scope, and a group left empty disappears with them.
 * Pure so it can be unit-tested under plain Node.
 */
export function navForRoles(
  nav: ReadonlyArray<AdminNavGroup>,
  isOwner: boolean,
): ReadonlyArray<AdminNavGroup> {
  if (isOwner) return nav;
  return nav
    .map((group) => ({ ...group, items: group.items.filter((item) => !item.ownerOnly) }))
    .filter((group) => group.items.length > 0);
}

/**
 * Route prefixes whose pages are owner-only. The layout swaps the page for an
 * "Owner only" panel when an admin without the owner scope lands here — the
 * BFF 404s their data anyway, so this is the honest state, not a guard.
 * `/admin/coach-payslip` and `/admin/session-economics` are legacy redirects
 * into owner-only destinations and are listed so the redirect frame is not
 * shown to a non-owner either.
 */
export const OWNER_ONLY_ROUTE_PREFIXES: ReadonlyArray<string> = [
  "/admin/payouts",
  "/admin/reports",
  "/admin/audit-logs",
  "/admin/coach-payslip",
  "/admin/session-economics",
];

/**
 * Exceptions carved out of `OWNER_ONLY_ROUTE_PREFIXES`: dues follow-up is
 * operations work (chasing balances), so admins keep it even though it lives
 * under `/admin/reports`.
 */
export const OWNER_ONLY_ROUTE_EXCEPTIONS: ReadonlyArray<string> = ["/admin/reports/dues"];

const matchesPrefix = (pathname: string, prefix: string) =>
  pathname === prefix || pathname.startsWith(prefix + "/");

/** True when `pathname` is an owner-only page (see the prefix list above). */
export function isOwnerOnlyRoute(pathname: string): boolean {
  if (OWNER_ONLY_ROUTE_EXCEPTIONS.some((prefix) => matchesPrefix(pathname, prefix))) {
    return false;
  }
  return OWNER_ONLY_ROUTE_PREFIXES.some((prefix) => matchesPrefix(pathname, prefix));
}

export interface AdminScreenMeta {
  title: string;
  subtitle: string;
  breadcrumbs: ReadonlyArray<string>;
}

/**
 * Per-route topbar metadata. Subtitles are static descriptors, not
 * data-driven counts. Pages that need live numbers (e.g. "3 pending
 * approvals") should expose them in their own page body.
 */
export const SCREEN_META: Record<string, AdminScreenMeta> = {
  "/admin": { title: "Dashboard", subtitle: "Daily overview", breadcrumbs: ["Admin", "Dashboard"] },
  "/admin/dashboard": { title: "Dashboard", subtitle: "Daily overview", breadcrumbs: ["Admin", "Dashboard"] },
  "/admin/sessions": { title: "Sessions", subtitle: "Schedule and rosters", breadcrumbs: ["Admin", "Sessions"] },
  "/admin/students": { title: "Students", subtitle: "Roster and enrollment", breadcrumbs: ["Admin", "Students"] },
  "/admin/pathway": { title: "Skill Pathways", subtitle: "Curriculum levels and skills", breadcrumbs: ["Admin", "Pathway"] },
  "/admin/users": { title: "Users", subtitle: "Coaches, parents, and admins", breadcrumbs: ["Admin", "Users"] },
  "/admin/registrations": { title: "Admissions", subtitle: "Registrations, waitlist, level-ups", breadcrumbs: ["Admin", "Admissions"] },
  "/admin/requests": { title: "Requests", subtitle: "Makeups, trials, absences, cancellations, pauses", breadcrumbs: ["Admin", "Requests"] },
  "/admin/payments": { title: "Payments", subtitle: "Transactions and refunds", breadcrumbs: ["Admin", "Money", "Payments"] },
  "/admin/billing-health": { title: "Billing Health", subtitle: "Reconciliation, failed payments, webhook recovery", breadcrumbs: ["Admin", "Money", "Billing Health"] },
  "/admin/billing-setup": { title: "Billing Setup", subtitle: "Stripe registration status, invites, and charging", breadcrumbs: ["Admin", "Money", "Billing Setup"] },
  "/admin/expenses": { title: "Expenses", subtitle: "Categorised academy spend", breadcrumbs: ["Admin", "Money", "Expenses"] },
  "/admin/payouts": { title: "Payroll & payouts", subtitle: "Payout cycles and coach payslips", breadcrumbs: ["Admin", "Money", "Payouts"] },
  "/admin/reports": { title: "Reports", subtitle: "Exports and summaries", breadcrumbs: ["Admin", "Money", "Reports"] },
  "/admin/reports/session-economics": { title: "Session economics", subtitle: "Revenue, cost, and profit by session", breadcrumbs: ["Admin", "Money", "Reports", "Session economics"] },
  "/admin/reports/dues": { title: "Dues follow-up", subtitle: "Outstanding balances", breadcrumbs: ["Admin", "Money", "Reports", "Dues"] },
  "/admin/reports/refunds": { title: "Refunds & credits", subtitle: "Money returned and account credits by month", breadcrumbs: ["Admin", "Money", "Reports", "Refunds & credits"] },
  "/admin/reports/revenue-by-category": { title: "Revenue by category", subtitle: "Collected revenue split by program and fee category", breadcrumbs: ["Admin", "Money", "Reports", "Revenue by category"] },
  "/admin/reports/deposit-slip": { title: "Deposit slip", subtitle: "Payments received by day and method for bank reconciliation", breadcrumbs: ["Admin", "Money", "Reports", "Deposit slip"] },
  "/admin/messages": { title: "Messages", subtitle: "Inbox and broadcasts", breadcrumbs: ["Admin", "Comms", "Messages"] },
  "/admin/waivers": { title: "Waivers", subtitle: "Student signatures and expiry", breadcrumbs: ["Admin", "Comms", "Waivers"] },
  "/admin/settings": { title: "Settings", subtitle: "Academy preferences", breadcrumbs: ["Admin", "Settings"] },
  "/admin/audit-logs": { title: "Audit logs", subtitle: "Recent admin actions", breadcrumbs: ["Admin", "Audit logs"] },
};

const FALLBACK_META: AdminScreenMeta = {
  title: "Admin",
  subtitle: "",
  breadcrumbs: ["Admin"],
};

/** Resolve topbar metadata for a pathname. Falls back to a safe default. */
export function metaForPath(pathname: string): AdminScreenMeta {
  if (SCREEN_META[pathname]) return SCREEN_META[pathname];
  // Dynamic segments (e.g. /admin/sessions/[id]) — match by longest prefix.
  const keys = Object.keys(SCREEN_META).sort((a, b) => b.length - a.length);
  for (const key of keys) {
    if (pathname.startsWith(key + "/")) {
      const base = SCREEN_META[key];
      return { ...base, breadcrumbs: [...base.breadcrumbs, "Detail"] };
    }
  }
  return FALLBACK_META;
}
