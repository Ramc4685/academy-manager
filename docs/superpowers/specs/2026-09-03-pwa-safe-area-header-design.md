# PWA safe-area header fix — design

**Date:** 2026-09-03
**Scope:** small PR, ships ahead of the wider mobile-usability pass for admin and coach.

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

## Non-goals (next PR)

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

### 1. Safe-area utilities

Add to `tailwind.config.ts` under `theme.extend.padding`:

- `safe-top`: `env(safe-area-inset-top, 0px)`
- `safe-bottom`: `env(safe-area-inset-bottom, 0px)`

Headers that already carry `py-3` need the inset *added* to their padding, not replacing
it, so they use an explicit arbitrary value: `pt-[calc(0.75rem+env(safe-area-inset-top,0px))]`
with `pb-3`. This is intentionally verbose so it is greppable.

### 2. Elements that get the inset

| File | Element | Change |
| --- | --- | --- |
| `app/(admin)/layout.tsx` `RallyTopbar` | sticky header | `py-3` → `pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]` |
| `app/(admin)/layout.tsx` `MobileDrawer` | drawer `<aside>` | add `pt-safe-top` |
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
On open it reads the menu's bounding rect once (layout effect) and, if the left edge is
off-screen, flips the anchor to `left: 0; right: auto`; if the right edge is off-screen it
keeps `right: 0`. It resets inline styles when the menu closes. Used by
`PersonaSwitcher` and `TenantSwitcher`. No positioning library.

### 4. Tests

- Vitest: `use-clamp-menu.test.tsx` renders a menu with a mocked
  `getBoundingClientRect` returning a negative left and asserts the inline style flips;
  a rect fully on screen leaves styles untouched.
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
