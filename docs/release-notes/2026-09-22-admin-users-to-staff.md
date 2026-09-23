# admin-users-to-staff

PR: #921

## What changed

- `/admin/users` is now **Staff**: nav label, page title, subtitle ("Coaches and admins: logins, roles, pay") and breadcrumbs `Admin / People / Staff`. The nav id stays `users`, so the `admin-nav-users` testid and every existing deep link keep working.
- The role pills are **All staff / Coaches / Assistant coaches / Admins**. The Parents pill is gone. "All staff" asks the BFF for `exclude_role=parent` (#918), so parent-only accounts drop out while a coach who is also a parent stays. That read lives under its own query key and no longer shares the unfiltered users cache used by People search and the roles panel.
- `/admin/users?role=parent` still works: it lists parent accounts (including parents with no children yet) behind a "Parents now live in Families" banner with no pill selected. Browsers that cached the old permanent redirect from `/admin/parents` land here and are pointed the right way.
- A help line under the pills says where pay rates and session assignment live (each coach's page), links owners to Coach payouts, and links "Parent accounts live under Families" to `/admin/families`. Adding a parent from Staff shows a notice with a link to the new account, since that row will not appear in the Staff list.
- The user detail page shows a one-line banner on parent-only accounts ("This is a parent account, not staff") linking to the family record.
- `/admin/parents` now redirects to `/admin/families` (in `next.config.ts` as a temporary 307 and in the fallback page). `/admin/coaches` is unchanged. Route count is unchanged at 92; no route was added or removed.
- Tests: new `lib/admin/staff-filters.test.ts`, a Staff case in `screen-meta.test.ts`, the redirect pin in `next.config.test.ts`, and `admin-shell.spec.ts` gains specs for the Families landing, the `?role=parent` banner, and All staff keeping a coach-who-is-also-a-parent.

## Deploy notes

None. Frontend only; no migration, no env change, no backend change. Depends on #918 already being live (it is), otherwise "All staff" would ignore the unknown `exclude_role` param and show parents again, which is harmless.

## Risk / rollback

Low. Revert the PR to restore the Users label, the Parents pill and the old redirect. The new `/admin/parents` redirect is `permanent: false` on purpose, so a rollback is not pinned in anyone's browser. What admins will notice: bookmarks to `/admin/parents` now land on Families instead of the parent list; a browser that cached the old 308 still opens `/admin/users?role=parent`, which keeps listing parents with a banner pointing at Families. Parents with no children yet are only reachable through that `?role=parent` URL until a Families view for them exists (spec §3.3).
