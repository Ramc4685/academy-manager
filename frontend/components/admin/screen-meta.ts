/**
 * Rally admin navigation + per-route topbar metadata.
 *
 * Subtitles are static — the shell does NOT fetch data. Pages that
 * want to surface live counts in the topbar should use AdminActionSlot
 * or render their own header inside the page body.
 */

export type AdminNavIconKey =
  | "home" | "calendar" | "user" | "users" | "family" | "badge" | "list" | "check"
  | "attend" | "pay" | "card" | "bell" | "whistle" | "chart"
  | "msg" | "cog" | "trophy" | "signal" | "filter";

export interface AdminNavItem {
  /**
   * Stable identifier, unique across the nav. It is the `admin-nav-<id>`
   * testid, so it must not change when a label is reworded or an item moves
   * to another group (sidebar regroup spec §2.3).
   */
  id: string;
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
 * Rally admin nav in six groups (sidebar regroup spec §2): the day's start
 * point, the curriculum, the people, outbound comms, the money, and the
 * academy's own configuration. Every item carries an explicit `id` so the
 * testid survives a label change; "Staff" (formerly "Users") keeps the id `users`.
 */
export const ADMIN_NAV: ReadonlyArray<AdminNavGroup> = [
  {
    group: "TODAY",
    items: [
      { id: "dashboard", href: "/admin", label: "Dashboard", icon: "home", match: eq("/admin") },
      // Inbox is the second thing an admin opens each day; it sits under
      // Dashboard rather than sixth in a work list.
      { id: "inbox", href: "/admin/inbox", label: "Inbox", icon: "check", match: startsWith("/admin/inbox") },
    ],
  },
  {
    group: "CLASSES",
    items: [
      { id: "sessions", href: "/admin/sessions", label: "Sessions", icon: "calendar", match: startsWith("/admin/sessions") },
      { id: "pathway", href: "/admin/pathway", label: "Pathway", icon: "trophy", match: startsWith("/admin/pathway") },
    ],
  },
  {
    group: "PEOPLE",
    items: [
      // #839: one person, a household, and (badge) the staff who wear a
      // lanyard. Three People destinations, three glyphs.
      { id: "students", href: "/admin/students", label: "Students", icon: "user", match: startsWith("/admin/students") },
      { id: "families", href: "/admin/families", label: "Families", icon: "family", match: startsWith("/admin/families") },
      { id: "users", href: "/admin/users", label: "Staff", icon: "badge", match: startsWith("/admin/users") },
    ],
  },
  {
    group: "REACH",
    items: [
      { id: "messages", href: "/admin/messages", label: "Messages", icon: "msg", match: startsWith("/admin/messages") },
    ],
  },
  {
    group: "MONEY",
    items: [
      // Ordered by how often the job is done: work the money list, close the
      // month, then the plumbing and the outgoings.
      { id: "payments", href: "/admin/payments", label: "Payments", icon: "pay", match: startsWith("/admin/payments") },
      { id: "month-close", href: "/admin/reports", label: "Month close", icon: "chart", match: startsWith("/admin/reports"), ownerOnly: true },
      { id: "billing-health", href: "/admin/billing-health", label: "Billing Health", icon: "signal", match: startsWith("/admin/billing-health"), ownerOnly: true },
      { id: "expenses", href: "/admin/expenses", label: "Expenses", icon: "card", match: startsWith("/admin/expenses") },
      { id: "coach-payouts", href: "/admin/payouts", label: "Coach payouts", icon: "whistle", match: startsWith("/admin/payouts"), ownerOnly: true },
    ],
  },
  {
    group: "ACADEMY",
    items: [
      // Waivers shared Inbox's `check` glyph; `attend` is the signed sheet.
      { id: "waivers", href: "/admin/waivers", label: "Waivers", icon: "attend", match: startsWith("/admin/waivers") },
      { id: "settings", href: "/admin/settings", label: "Settings", icon: "cog", match: startsWith("/admin/settings") },
      { id: "audit-logs", href: "/admin/audit-logs", label: "Audit logs", icon: "filter", match: startsWith("/admin/audit-logs"), ownerOnly: true },
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
  // Stripe plumbing is governance, the same tier as Reports and Payouts
  // (billing-health trim spec §2).
  "/admin/billing-health",
  "/admin/payouts",
  "/admin/reports",
  "/admin/audit-logs",
  "/admin/coach-payslip",
  "/admin/session-economics",
];

/**
 * Exceptions carved out of `OWNER_ONLY_ROUTE_PREFIXES`.
 *
 * `/admin/reports/dues` stays listed even though the Dues page is gone (month
 * close spec §6). It is now a redirect to `/admin/payments`, and `/admin/reports`
 * is owner-only, so removing the exception would meet an admin following an old
 * bookmark with an owner-only wall instead of forwarding them to a page they are
 * allowed to use. The exception keeps the redirect reachable by whoever the
 * target is reachable by.
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
  "/admin/students": { title: "Students", subtitle: "Every child: classes, attendance, status", breadcrumbs: ["Admin", "People", "Students"] },
  "/admin/pathway": { title: "Skill Pathways", subtitle: "Curriculum levels and skills", breadcrumbs: ["Admin", "Pathway"] },
  "/admin/users": { title: "Staff", subtitle: "Coaches and admins: logins, roles, pay", breadcrumbs: ["Admin", "People", "Staff"] },
  "/admin/inbox": { title: "Inbox", subtitle: "Registrations, waitlist, level-ups, and parent requests", breadcrumbs: ["Admin", "Inbox"] },
  // The registration detail page is the one route left under /admin/registrations
  // now that the list redirects to the Inbox (#776); without its own key it would
  // fall through to the generic fallback title.
  "/admin/registrations/[applicationId]": { title: "Registration", subtitle: "Review and decide", breadcrumbs: ["Admin", "Inbox", "Registration"] },
  "/admin/payments": { title: "Payments", subtitle: "Who owes, who is charged, who paid", breadcrumbs: ["Admin", "Money", "Payments"] },
  "/admin/billing-health": { title: "Billing Health", subtitle: "Connect readiness, webhooks, reconciliation", breadcrumbs: ["Admin", "Money", "Billing Health"] },
  "/admin/families": { title: "Families", subtitle: "Each family: children, balance, card, autopay", breadcrumbs: ["Admin", "People", "Families"] },
  "/admin/families/[parentId]": { title: "Family", subtitle: "Balance, autopay, invoices and what the system did", breadcrumbs: ["Admin", "People", "Families", "Family"] },
  "/admin/expenses": { title: "Expenses", subtitle: "Categorised academy spend", breadcrumbs: ["Admin", "Money", "Expenses"] },
  "/admin/payouts": { title: "Payroll & payouts", subtitle: "Payout cycles and coach payslips", breadcrumbs: ["Admin", "Money", "Payouts"] },
  "/admin/reports": { title: "Month close", subtitle: "The month's two runs, its money, and anything odd", breadcrumbs: ["Admin", "Money", "Month close"] },
  "/admin/reports/session-economics": { title: "Session economics", subtitle: "Revenue, cost, and profit by session", breadcrumbs: ["Admin", "Money", "Month close", "Session economics"] },
  "/admin/reports/refunds": { title: "Refunds & credits", subtitle: "Money returned and account credits by month", breadcrumbs: ["Admin", "Money", "Month close", "Refunds & credits"] },
  "/admin/reports/revenue-by-category": { title: "Revenue by category", subtitle: "Collected revenue split by program and fee category", breadcrumbs: ["Admin", "Money", "Month close", "Revenue by category"] },
  "/admin/reports/deposit-slip": { title: "Deposit slip", subtitle: "Payments received by day and method for bank reconciliation", breadcrumbs: ["Admin", "Money", "Month close", "Deposit slip"] },
  "/admin/messages": { title: "Messages", subtitle: "Broadcasts, direct messages, email campaigns", breadcrumbs: ["Admin", "Reach", "Messages"] },
  "/admin/waivers": { title: "Waivers", subtitle: "Student signatures and expiry", breadcrumbs: ["Admin", "Academy", "Waivers"] },
  "/admin/settings": { title: "Settings", subtitle: "Academy preferences", breadcrumbs: ["Admin", "Settings"] },
  "/admin/audit-logs": { title: "Audit logs", subtitle: "Recent admin actions", breadcrumbs: ["Admin", "Audit logs"] },
};

const FALLBACK_META: AdminScreenMeta = {
  title: "Admin",
  subtitle: "",
  breadcrumbs: ["Admin"],
};

const isDynamicSegment = (segment: string) => segment.startsWith("[") && segment.endsWith("]");

/**
 * True when a SCREEN_META key with bracketed segments (e.g.
 * `/admin/families/[parentId]`) matches `pathname` segment for segment.
 */
function matchesDynamicKey(key: string, pathname: string): boolean {
  const keyParts = key.split("/");
  const pathParts = pathname.split("/");
  if (keyParts.length !== pathParts.length) return false;
  return keyParts.every(
    (part, i) => (isDynamicSegment(part) ? pathParts[i].length > 0 : part === pathParts[i]),
  );
}

/** Resolve topbar metadata for a pathname. Falls back to a safe default. */
export function metaForPath(pathname: string): AdminScreenMeta {
  if (SCREEN_META[pathname]) return SCREEN_META[pathname];
  const keys = Object.keys(SCREEN_META).sort((a, b) => b.length - a.length);
  // Explicit dynamic keys (e.g. /admin/families/[parentId]) carry their own
  // title and breadcrumbs.
  for (const key of keys) {
    if (key.includes("[") && matchesDynamicKey(key, pathname)) return SCREEN_META[key];
  }
  // Otherwise match by longest static prefix and append "Detail".
  for (const key of keys) {
    if (key.includes("[")) continue;
    if (pathname.startsWith(key + "/")) {
      const base = SCREEN_META[key];
      return { ...base, breadcrumbs: [...base.breadcrumbs, "Detail"] };
    }
  }
  return FALLBACK_META;
}
