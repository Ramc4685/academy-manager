# PWA safe-area header fix — design

**Date:** 2026-09-03
**Scope:** PR #647. Originally the safe-area fix alone; on 2026-09-03 the user asked to pack the
follow-ups into the same PR. Part A below is merged into the branch already; Part B is the
expanded scope.

## Problem

The app is installed to the iPhone home screen (manifest `display: standalone`).
`app/layout.tsx` sets `appleWebApp.statusBarStyle: "black-translucent"` and
`viewport.viewportFit: "cover"`, which tells iOS to draw the page under the status bar.
That is the correct native-feeling configuration, but it requires every element pinned
to the top of the screen to pad itself by `env(safe-area-inset-top)`. Nothing in the app
does. The coach bottom nav already pads by `env(safe-area-inset-bottom)`, so the bottom
edge is fine.

Result, observed in screenshots on iOS 26:

1. Every persona shell header (admin, coach, parent, student, platform) renders in the
   status-bar zone. iOS applies its glass blur to that zone and routes taps there to the
   OS, so the view switcher, academy switcher, logout, calendar and messages buttons are
   visible but unreachable. In Safari this is masked because Safari reserves the status
   bar itself.
2. When a tap does land (the lower edge of a button pokes below the zone), the persona
   switcher menu opens off the left edge of the screen. The menu is `absolute right-0`
   and 176px wide, anchored to a button that sits near the left edge on phones. The
   tenant switcher menu (256px, same anchoring) has the same defect.

## Part A — safe-area fix (done on branch)

See sections 1–4 below.

## Originally deferred (now Part B, in this PR)

- Reorganising the admin topbar's right-hand cluster (view switcher, academy switcher,
  Refresh, logout) which overflows the phone width and pushes the page title out.
  Target pattern: topbar keeps menu button, title, and one page action; account-level
  controls move to the drawer footer.
- Back navigation on every non-top-level page (e.g. coach Skill Passport, admin
  session/student detail). The installed app has no browser chrome and the iOS edge
  swipe is unreliable in standalone mode, so shell headers need a back chevron on
  detail routes with a parent-route fallback for deep links. Own PR, next.
- Per-page mobile layouts (tables to cards, filters, row actions).

## Design

### 1. Safe-area values

The frontend is Tailwind 4 (CSS-first) loading a legacy `tailwind.config.ts` via
`@config`. Rather than register named utilities in two places, use arbitrary values,
which are explicit and greppable:

- Headers that already carry `py-3` need the inset *added* to their padding:
  `pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]`.
- Elements with no existing top padding: `pt-[env(safe-area-inset-top,0px)]`.
- Toast container: `bottom-[max(1rem,env(safe-area-inset-bottom,0px))]`.

### 2. Elements that get the inset

| File | Element | Change |
| --- | --- | --- |
| `app/(admin)/layout.tsx` `RallyTopbar` | sticky header | `py-3` → `pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]` |
| `app/(admin)/layout.tsx` `MobileDrawer` | drawer `<aside>` | add `pt-[env(safe-area-inset-top,0px)]` |
| `app/(coach)/layout.tsx` | sticky header | same as admin header |
| `app/(parent)/layout.tsx` | sticky header | same |
| `app/(student)/layout.tsx` | sticky header | same |
| `app/(platform)/layout.tsx` | sticky header | same |
| `components/ds/toast.tsx` | toast container | `bottom-4` → `bottom-[max(1rem,env(safe-area-inset-bottom,0px))]` |

Because the header background extends under the status bar, the status bar sits on the
header colour (dark for coach/parent/student/platform, white for admin), which is the
standard installed-app look. Centred modals and the drawer's full-screen scrim need no
change.

### 3. Dropdown menus stay on screen

Add a hook `useClampMenuToViewport(ref, open)` in `components/persona/use-clamp-menu.ts`.
The decision is a pure function `shouldAnchorLeft(rect, margin)` in
`components/persona/menu-anchor.ts` (unit-testable in the node vitest environment). The
hook runs a layout effect when the menu opens, reads the menu's bounding rect once and,
if the left edge is inside the margin, sets inline `left: 0; right: auto`. The menu is
conditionally rendered, so closing unmounts it and no reset is needed. Used by
`PersonaSwitcher` and `TenantSwitcher`. No positioning library.

### 4. Tests

- Vitest: `menu-anchor.test.ts` covers `shouldAnchorLeft` for an off-screen left edge,
  an edge inside the margin, and a fully on-screen rect. (The vitest environment is
  node with no DOM library, so the hook itself is not rendered in tests.)
- Vitest: a small shell-header test asserts each of the five layout files contains the
  safe-area padding token (string-level guard, since the layouts need auth to render).
  Cheap, and it fails loudly if someone reverts `py-3`.
- Manual: install the app on the iOS simulator (Safari → Share → Add to Home Screen),
  open admin and coach, confirm the header content sits below the status bar and the
  view switcher opens fully on screen. Playwright cannot emulate safe-area insets, so
  this is not an e2e check.

## Risks

- Desktop browsers resolve `env(safe-area-inset-top)` to 0, so nothing changes there.
- Android Chrome installed PWAs also honour the inset; the change is correct there too.


---

# Part B — back navigation, admin account controls, table overflow

## B1. Back navigation on every non-top-level page

**Why:** the installed app has no browser chrome and the iOS edge-swipe is unreliable in
standalone mode. A coach on the Skill Passport page has no way back except the bottom tabs.

**Shared pieces** (`frontend/components/persona/`):

- `parent-route.ts` — pure: `parentRoute(pathname: string, known: readonly string[], home: string): string`.
  Strips trailing path segments one at a time and returns the first prefix found in `known`;
  returns `home` if none. `isTopLevel(pathname, known)` returns true when `pathname` (trailing
  slash stripped) is exactly in `known`. Unit-tested in `parent-route.test.ts` (node vitest).
- `back-button.tsx` — `ShellBackButton({ known, home, variant })`. Uses `usePathname`. Renders
  nothing when `isTopLevel`. Otherwise renders a `<button type="button" aria-label="Back"
  data-testid="shell-back-button">` of at least 44×44 (`min-h-touch min-w-touch`) with an inline
  chevron-left SVG (no icon library). `variant: "light" | "dark"` picks text colour
  (`text-rally-muted` on light, `text-slate-300` on dark). On click: if
  `window.history.length > 1` call `router.back()`, else `router.push(parentRoute(...))`.
  This is the standard PWA heuristic; a deep-linked launch has history length 1.

**Known (top-level) route lists** — exported as `const` arrays next to each shell, passed to
`ShellBackButton`:

| Shell | known | home |
| --- | --- | --- |
| admin | every `href` in `ADMIN_NAV` (export `adminTopLevelRoutes()` from `components/admin/screen-meta.ts`), plus `/admin/dashboard` | `/admin` |
| coach | `/coach/dashboard`, `/coach/today`, `/coach/sessions`, `/coach/profile`, `/coach/calendar`, `/coach/messages`, `/coach/needs-review` | `/coach/dashboard` |
| parent | `/parent/dashboard`, `/parent/children`, `/parent/payments`, `/parent/progress`, `/parent/calendar`, `/parent/messages`, `/parent/profile`, `/parent/attendance`, `/parent/requests`, `/parent/waivers`, `/parent/onboarding` | `/parent/dashboard` |
| student | `/student/dashboard`, `/student/progress`, `/student/schedule` | `/student/dashboard` |
| platform | `/platform`, `/platform/tenants` | `/platform/tenants` |

Examples: `/coach/students/abc/passport` → known has no `/coach/students` → falls to
`/coach/dashboard`. `/coach/sessions/abc/skills` → `/coach/sessions`. `/admin/reports/dues` →
`/admin/reports`. `/admin/sessions/abc/skill-board` → `/admin/sessions`. `/parent/onboarding`
is top-level on purpose: it is a wizard with its own step navigation.

**Placement:** coach, parent, student, platform headers: the back button is the first child of
the header's left group, before the brand link. Admin `RallyTopbar`: after the hamburger,
before the title block, `variant="light"`. Hamburger stays.

## B2. Admin account controls move out of the topbar

**Why:** on a phone the topbar's right cluster (view switcher, academy switcher, Refresh,
logout) fills the width and pushes the title out (screenshot 1). Standard mobile admin
pattern: topbar = menu/back, title, one page action; account-level controls live in the
navigation surface.

- New `SidebarAccountSection` in `app/(admin)/layout.tsx`, rendered in BOTH `DesktopSidebar`
  and `MobileDrawer` directly above `SidebarUserPill`: `PersonaSwitcher current="admin"
  variant="dark"`, `TenantSwitcher variant="dark"`, and `PersonaLogoutButton` as a full-width
  row with its label visible. It sits OUTSIDE the drawer's `<nav onClick={onClose}>` so opening
  a menu does not close the drawer.
- `TenantSwitcher` gains `variant?: "light" | "dark"` (default light) mirroring the persona
  switcher's dark button classes; the single-tenant label and the menu keep their testids.
- `RallyTopbar` no longer renders `PersonaSwitcher`, `TenantSwitcher`, or
  `PersonaLogoutButton` at any width. It keeps hamburger, back button, title block,
  `AdminActionSlotOutlet`, offline pill, Refresh. Its props drop nothing else.
- To avoid duplicate testids (the desktop sidebar is CSS-hidden on phones but still in the
  DOM), `AdminLayout` renders exactly one sidebar tree: `useIsDesktop()` (new hook in
  `lib/use-is-desktop.ts`, `useSyncExternalStore` over `matchMedia("(min-width: 1024px)")`,
  server snapshot `false`) → `isDesktop ? <DesktopSidebar/> : drawerOpen && <MobileDrawer/>`.
  The layout already renders "Loading…" until auth resolves, so there is no SSR flash.
- The drawer closes automatically when `pathname` changes (`useEffect`), so a tenant or
  persona switch from the drawer does not leave it hanging open.

**e2e updates in `e2e/specs/admin-shell.spec.ts`:** every interaction with
`tenant-switcher-*`, `persona-switcher-*` or the admin `persona-logout-button` first calls
`openAdminNav(page)` and scopes the locator to the returned surface (`nav.getByTestId(...)`),
so the tests pass on both the desktop sidebar and the mobile drawer. `expectShellLogout` gets
an `openNav` flag used only for `/admin`. Add tests: (a) on a mobile project, the admin topbar
has no `persona-switcher-button`/`tenant-switcher-button` outside the drawer; (b)
`/coach/sessions/<id>` shows `shell-back-button` and clicking it lands on `/coach/sessions`
when the page was opened directly (history length 1 → parent fallback); (c) `/coach/today`
shows no `shell-back-button`; (d) `/admin/sessions/<id>` shows the back button and `/admin`
does not.

## B3. Table overflow

Wrap the three tables that lacked a horizontal scroll container in
`<div className="overflow-x-auto">`: `app/(admin)/admin/billing-setup/page.tsx`,
`app/(admin)/admin/payouts/page.tsx`, `components/admin/settings/notify-panel.tsx`. (Done
inline by the orchestrator.)

## Part B non-goals

Per-page card layouts for the 38 table-rendering files wait for screenshots of the specific
screens. Coach/parent header clusters are small enough to stay in the header.
