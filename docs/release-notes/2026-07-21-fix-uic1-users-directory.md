# fix-uic1-users-directory

PR: #324

## What changed
The Coaches and Parents admin directories are merged into a single **Users**
screen. `/admin/users` is now the canonical route: `AdminUsersDirectory` renders
its built-in role pills (All / Coaches / Parents / Admins) as tabs, with the
active tab driven by a `?role=coach|parent|admin` query param (URL is the single
source of truth). The coach engagement stats strip moved out of the old coaches
page into `components/admin/CoachEngagementStatsStrip.tsx` and now renders only
while the Coaches tab is active.

Old URLs keep working: `/admin/coaches` → `/admin/users?role=coach` and
`/admin/parents` → `/admin/users?role=parent` are server-side `redirect()`
stubs. The admin nav drops the two Coaches/Parents items for one **Users** item
(net −1 nav item), and the previously orphaned superset page is now reachable
from the nav. Gutting the old `/admin/users` page also removed its duplicate
table + `mapRoleToStatus` copy (audit item QW8).

## Deploy notes
none — frontend-only, no migrations, no env changes, backend untouched.
`/admin/users/new` and `/admin/users/[userId]` are unchanged.

## Risk / rollback
Low. Redirect stubs and the nav change are pure code and trivially revertible
(`git revert`). `SCREEN_META` retains a safe fallback for any unmapped path. If
the role param is absent or invalid, the directory defaults to the All tab.
