# UIC6 — Registrations + Waitlist + Level-up queue → Admissions screen
Status: TODO
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem
Three small queue pages with identical list-review/approve UX occupy separate routes; one is orphaned:
- `/admin/registrations` (99L) — pending parent applications table, links to `registrations/[applicationId]` review detail.
- `/admin/waitlist` (159L) — global waitlist grouped by session, metrics header.
- `/admin/level-up-queue` (220L) — coach level-up recommendations approve/reject. **Orphan: no inbound link anywhere** (grep: only referenced by itself and `lib/api/curriculum.ts`; not in `screen-meta.ts` nav).

## Current behavior (verified)
- `registrations/page.tsx`: `queryKeys.admin.registrations()` + `listAdminRegistrations`; `data-testid="admin-registrations"`; subroute `[applicationId]` is the actual approval flow (PR #302 defect fixes live there — don't touch).
- `waitlist/page.tsx`: `queryKeys.admin.globalWaitlist()` + `listGlobalWaitlist`; `data-testid="admin-waitlist"`.
- `level-up-queue/page.tsx`: `["admin","level-up-queue"]` + `getLevelUpQueue`/`approveLevelUp`/`rejectLevelUp` from `lib/api/curriculum`; `data-testid="admin-level-up-queue"`.
- Nav: `screen-meta.ts:53` (Registrations), `:54` (Waitlist); no level-up item. Meta `:115-116`.
- e2e: `admin-shell.spec.ts:78-79` and `saas-launch-route-matrix.spec.ts:92-96` visit `/admin/registrations` + `/admin/waitlist`; `local-auth-inventory.spec.ts:92` covers `registrations/[applicationId]`; `admin-registrations.spec.ts` covers the review flow.

## Proposed change (target IA)
One nav item **Admissions** at canonical route **`/admin/registrations`** (keeps the `[applicationId]` subroute co-located and one old URL needs no redirect) with three tabs (requests-page tablist pattern, `?tab=` deep link):
**Registrations** (default) · **Waitlist** · **Level-ups**.
- `/admin/waitlist` → redirect `/admin/registrations?tab=waitlist`
- `/admin/level-up-queue` → redirect `/admin/registrations?tab=level-ups` (orphan rescued into nav)
- Nav: Registrations + Waitlist items replaced by one "Admissions" item (net −1, and level-ups become reachable).

## Implementation steps
1. Extract each page body into `components/admin/admissions/RegistrationsTab.tsx`, `WaitlistTab.tsx`, `LevelUpsTab.tsx` (move code as-is: query keys, testids on each panel root, mutations). Fix the `any` in level-up chip mapping while moving.
2. Rewrite `app/(admin)/admin/registrations/page.tsx` as the tab shell: `type AdmissionsTab = "registrations" | "waitlist" | "level-ups"`, tablist markup copied from `admin/requests/page.tsx:69-87`, init from `useSearchParams().get("tab")`. Keep `data-testid="admin-registrations"` on the shell (plus per-tab testids) so existing selectors survive.
3. Redirect stubs: `app/(admin)/admin/waitlist/page.tsx` → `redirect("/admin/registrations?tab=waitlist")`; `app/(admin)/admin/level-up-queue/page.tsx` → `redirect("/admin/registrations?tab=level-ups")`.
4. `screen-meta.ts`: replace items `:53-54` with `{ href: "/admin/registrations", label: "Admissions", icon: "check", match: startsWith("/admin/registrations") }`; delete `SCREEN_META["/admin/waitlist"]`; retitle `:115` to "Admissions" subtitle "Registrations, waitlist, level-ups"; drop the standalone waitlist meta.
5. e2e: `admin-shell.spec.ts:79` + `saas-launch-route-matrix.spec.ts:96` waitlist rows → assert redirect or new URL (keep `**/api/v2/admin/waitlist` stubs); add a level-ups tab smoke (stub the level-up-queue endpoint); `admin-registrations.spec.ts` and `local-auth-inventory.spec.ts:92` (detail route) should pass unchanged since `/admin/registrations` and `[applicationId]` remain.

## Files to change / delete
- `frontend/app/(admin)/admin/registrations/page.tsx` (→ Admissions tab shell)
- `frontend/components/admin/admissions/{RegistrationsTab,WaitlistTab,LevelUpsTab}.tsx` (new, moved code)
- `frontend/app/(admin)/admin/waitlist/page.tsx` (→ redirect stub)
- `frontend/app/(admin)/admin/level-up-queue/page.tsx` (→ redirect stub)
- `frontend/components/admin/screen-meta.ts`
- `frontend/e2e/specs/admin-shell.spec.ts`, `frontend/e2e/specs/saas-launch-route-matrix.spec.ts`

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Manually: registration review flow (`[applicationId]`) end-to-end unchanged; waitlist/level-up redirects land on the right tab; level-up approve/reject invalidates its queue. Backend untouched (all three APIs unchanged) — audit-inventory manifest backend-side unaffected.

## Risks / rollback
- Registrations detail flow just had defect fixes (PR #302) — shell rewrite must not touch `[applicationId]`; run `admin-registrations.spec.ts` explicitly.
- Level-up tab is newly discoverable: expect real traffic to a previously dark screen; sanity-check its empty/error states.
- Rollback = git revert (all three standalone pages restored).

## PR checklist
- [ ] Release note: "New Admissions screen: registrations, waitlist and level-up queue in one place (old URLs redirect)"
- [ ] TRACKER.md: UIC6 → DONE + PR link
- [ ] This plan: Status → DONE (PR #NNN, date)
