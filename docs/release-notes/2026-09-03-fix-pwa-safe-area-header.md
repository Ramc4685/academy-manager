# fix-pwa-safe-area-header

PR: #647

## What changed
Mobile usability pass for the installed (home-screen) app, prompted by
screenshots from an admin phone:

- **Headers were unreachable under the iOS status bar.** Every persona header
  (admin, coach, parent, student, platform) rendered under the status bar, so
  the view switcher, academy switcher, logout, calendar and messages buttons
  were blurred and could not be tapped. Headers, the admin drawer, and toasts
  now pad for the device safe areas.
- **Back button on every non-top-level page** in all five shells (e.g. coach
  Skill Passport, admin session/student detail). Uses browser history when
  there is any, otherwise jumps to the nearest known parent route, so a
  deep-linked launch still has a way back.
- **Admin account controls moved out of the topbar.** View switcher, academy
  switcher and logout now live at the bottom of the sidebar (desktop) and the
  drawer (phones). The topbar keeps menu, back, title and the page action, so
  it fits on a phone again. The drawer closes itself after a view or academy
  switch.
- The view and academy switcher menus stay on screen instead of opening off
  the left edge; three admin tables that lacked horizontal scroll
  (billing setup, payouts, notify log) now scroll sideways on narrow screens.
- Dev tooling: the local pre-push gate now skips the `webkit-mobile` Playwright
  shard by default. CI runs WebKit nightly and on e2e-touching PRs but does not
  require it to merge (#626); the local gate now matches. Use `--full` or
  `PRE_PUSH_E2E_ALL=1` to include it.

## Deploy notes
None. Pure frontend; no migration, no env vars. Installed users pick it up on
the next service-worker refresh (tap "Refresh" in the header if it appears,
or relaunch the app). Admins should be told the view/academy switchers and
logout are now in the sidebar / menu drawer.

## Risk / rollback
Low–medium. Desktop resolves safe-area insets to 0. The admin sidebar is now
mounted by a JS media query (64rem, matching Tailwind `lg:`) instead of CSS
only; if a desktop admin ever sees no sidebar, that hook is the first place
to look. Revert the PR to restore the previous headers and topbar.
