# fix-pwa-safe-area-header

PR: #647

## What changed
On phones with the app installed to the home screen, every persona header
(admin, coach, parent, student, platform) rendered under the iOS status bar,
so the view switcher, academy switcher, logout, calendar and messages buttons
were blurred and could not be tapped. Headers, the admin drawer, and toasts
now pad for the device safe areas. The view and academy switcher menus also
stay on screen instead of opening off the left edge.

## Deploy notes
None. Pure frontend CSS/layout; no migration, no env vars. Installed users
pick it up on the next service-worker refresh (tap "Refresh" in the header
if it appears, or relaunch the app).

## Risk / rollback
Low. Desktop browsers resolve the safe-area insets to 0, so nothing changes
there. Revert the PR to restore the previous headers.
