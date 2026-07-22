# UIC1 — Users directory: coaches + parents + users → one directory with role tabs
Status: DONE (PR #NNN, 2026-07-22)
Size: S · Depends on: none · Tracker: ../TRACKER.md

## Problem
Three top-level admin routes show the same people directory:
- `/admin/coaches` — 107L wrapper: `<AdminUsersDirectory fixedRole="coach" />` plus a `CoachEngagementStatsStrip` (7d/30d skill-outcome tiles).
- `/admin/parents` — 5L wrapper: `<AdminUsersDirectory fixedRole="parent" />`.
- `/admin/users` — 141L page with its **own duplicate** table implementation (incl. the duplicated `any`-typed `mapRoleToStatus`, see QW8), role pill filter (All/Coaches/Parents/Admins), and it is **not in the nav** (orphaned superset). Its subroutes `/admin/users/new` and `/admin/users/[userId]` are the real create/detail screens everything links to.

Two nav items burned on wrappers; the superset page is unreachable except by URL.

## Current behavior (verified)
- `components/admin/AdminUsersDirectory.tsx` (317L) already supports both modes: `fixedRole?: "coach" | "parent"` prop; when unset it renders the role pill filter (All/Coaches/Parents/Admins) itself (lines 22-60). Uses `queryKeys.admin.users(role)` + `listAdminUsers` from `lib/api/admin.ts`, has an "Add user/coach/parent" create dialog, rows link to `/admin/users/{id}`.
- Nav: `components/admin/screen-meta.ts:51-52` (Coaches, Parents items), no Users item. `SCREEN_META` entries at `:112-114` (`/admin/users` titled "Coaches & Parents", `/admin/coaches`, `/admin/parents`).
- e2e: `e2e/specs/admin-shell.spec.ts:77` and `e2e/specs/saas-launch-route-matrix.spec.ts:90` visit `/admin/users` expecting `data-testid="admin-users"`; `local-auth-inventory.spec.ts:86` covers `/admin/users/[userId]`. Both `AdminUsersDirectory` and the users page render `data-testid="admin-users"` today.

## Proposed change (target IA)
Canonical route: **`/admin/users`** — one "Users" screen rendering `AdminUsersDirectory` with **no** `fixedRole` (its built-in role pills become the tabs: All / Coaches / Parents / Admins). Support deep-linking via `?role=coach|parent|admin` so redirects land on the right tab. Move the coach engagement strip into the directory, shown only while the Coaches tab is active.
- `/admin/coaches` → redirect to `/admin/users?role=coach`
- `/admin/parents` → redirect to `/admin/users?role=parent`
- Nav: one "Users" item replaces Coaches + Parents (net −1 nav item, and the orphan superset gets rescued into nav).

## Implementation steps
1. `AdminUsersDirectory.tsx`: read `role` from `useSearchParams()` (fall back to state) and write it back with `router.replace`/`history.replaceState` on pill click (same pattern as `admin/settings/page.tsx:36-51` `?panel=`); accept an optional `coachExtras?: ReactNode` slot (or inline the strip) rendered when the active role is `coach`.
2. Move `CoachEngagementStatsStrip` (+ its helpers `getEngagementRanges`, `dateOnly`, `sumOutcomes`, `StatsTile`) out of `app/(admin)/admin/coaches/page.tsx` into `components/admin/CoachEngagementStatsStrip.tsx`; keep its `queryKeys.admin.coachEngagement` usage and `data-testid="coach-engagement-stats"`.
3. Replace `app/(admin)/admin/users/page.tsx` body (the 141L duplicate) with `<AdminUsersDirectory />` — this also completes QW8 (deletes one `mapRoleToStatus` copy). Keep `users/new` and `users/[userId]` untouched.
4. Replace `app/(admin)/admin/coaches/page.tsx` and `app/(admin)/admin/parents/page.tsx` with server-component redirect stubs: `import { redirect } from "next/navigation"; export default function Page() { redirect("/admin/users?role=coach"); }` (keeps bookmarks working; `/admin/coaches` had no subroutes, so a page-level redirect is sufficient).
5. `components/admin/screen-meta.ts`: remove Coaches (`:51`) and Parents (`:52`) nav items; add `{ href: "/admin/users", label: "Users", icon: "user", match: startsWith("/admin/users") }` in WORK. Update `SCREEN_META`: keep `/admin/users` (retitle "Users"), keep `/admin/coaches` + `/admin/parents` entries or delete them (routes now redirect before the shell renders — delete).
6. e2e: `admin-shell.spec.ts` and `saas-launch-route-matrix.spec.ts` already target `/admin/users` + `admin-users` testid — should pass unchanged; add one assertion that `/admin/coaches` lands on `/admin/users?role=coach` with the coach pill active and `coach-engagement-stats` visible.

## Files to change / delete
- `frontend/components/admin/AdminUsersDirectory.tsx` (role-from-URL + coach strip slot)
- `frontend/components/admin/CoachEngagementStatsStrip.tsx` (new, moved code)
- `frontend/app/(admin)/admin/users/page.tsx` (gut to directory render)
- `frontend/app/(admin)/admin/coaches/page.tsx` (→ redirect stub)
- `frontend/app/(admin)/admin/parents/page.tsx` (→ redirect stub)
- `frontend/components/admin/screen-meta.ts` (nav + meta)
- `frontend/e2e/specs/admin-shell.spec.ts`, `frontend/e2e/specs/saas-launch-route-matrix.spec.ts` (redirect assertions if nav items asserted)

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e` (frontend). Confirm `/admin/coaches`, `/admin/parents` 307→`/admin/users?...`; `/admin/users/new` and `/admin/users/[userId]` unaffected. Backend untouched — audit-inventory/route-matrix manifest expectations on `**/api/v2/admin/users*` stubs unchanged.

## Risks / rollback
- Risk: role pill state vs URL param double-source; mitigate by making URL the single source of truth. Redirect stubs are trivially revertible (git revert restores old pages).
- `SCREEN_META` fallback handles any missed path (safe default).

## PR checklist
- [x] Release note: "Coaches and Parents directories merged into Users (old URLs redirect)" — docs/release-notes/2026-07-21-fix-uic1-users-directory.md
- [x] TRACKER.md: UIC1 → DONE + PR link (QW8 was already DONE in #310 — the gutted /admin/users page used the shared roleToChipVariant, not a local mapRoleToStatus, so nothing to re-tick)
- [x] This plan: Status → DONE (PR #NNN, 2026-07-22)
