# UIC3 — Session economics + Dues follow-up → /admin/reports
Status: DONE (PR #TBD, 2026-07-23)
Size: M · Depends on: none · Tracker: ../TRACKER.md

## Problem
Four top-level MONEY nav items are all read-only financial analytics over the same ledger: `/admin/reports` (882L), `/admin/session-economics` (247L), `/admin/dues` (158L), plus `/admin/billing-health` (ops diagnostic — stays separate). Nav is at its scaling limit (24 items).

## Current behavior (verified)
- `app/(admin)/admin/reports/page.tsx` (882L) already hosts a hub-and-spoke pattern: dashboard KPIs + CSV exports on the hub, and three child **sub-routes** linked via `FINANCIAL_REPORTS` cards (lines 50-66): `reports/refunds`, `reports/revenue-by-category`, `reports/deposit-slip`. Each child has its own `SCREEN_META` entry (`screen-meta.ts:128-130`).
- `app/(admin)/admin/session-economics/page.tsx` (247L): `getAdminSessionEconomics(period)`, month picker, KPI grid + per-session table. Read-only. `data-testid="admin-session-economics"`.
- `app/(admin)/admin/dues/page.tsx` (158L): `listDuesFollowup` + `sendDuesReminders` mutation, row selection, and a **topbar action via `useAdminAction`** (`components/admin/admin-action-slot`). Not purely read-only (sends reminder emails). `data-testid="admin-dues"`.
- Nav: `screen-meta.ts:70` (Dues follow-up), `:79` (Session economics), `:80` (Reports). Meta `:122`, `:126-127`.
- e2e: `admin-shell.spec.ts:82` (`/admin/dues`), `saas-launch-route-matrix.spec.ts:103` (dues row); both stub `**/api/v2/admin/dues-followup*`. Reports hub covered elsewhere (`admin-reports` route matrix, PR #301).

## Proposed change (target IA)
Follow the **existing reports children pattern: sub-routes, not tabs** (the hub already links out to 3 sub-report pages; tabs would fight that established IA and the 882L hub file shouldn't absorb 400 more lines).
- Move page → `/admin/reports/session-economics` and `/admin/reports/dues`.
- Add both to the `FINANCIAL_REPORTS` card list on the hub (rename the section to "Detailed reports" if desired): "Session economics — revenue, cost and profit by session" and "Dues follow-up — outstanding balances and reminders".
- Old URLs `/admin/session-economics` and `/admin/dues` redirect to the new sub-routes.
- Nav: remove both items → MONEY group shrinks 9 → 7 (payslip removal in UIC4 makes it 6). Billing Health untouched.

## Implementation steps
1. `git mv app/(admin)/admin/session-economics/page.tsx app/(admin)/admin/reports/session-economics/page.tsx` (unchanged content); same for `dues` → `reports/dues`. The dues page's `useAdminAction` topbar button keeps working — the reports children render inside the same admin shell.
2. Create redirect stubs at the old paths: `app/(admin)/admin/session-economics/page.tsx` → `redirect("/admin/reports/session-economics")`; `app/(admin)/admin/dues/page.tsx` → `redirect("/admin/reports/dues")`.
3. `reports/page.tsx`: append two entries to `FINANCIAL_REPORTS` (lines 50-66) with the new hrefs. Note the hub already renders a dues-adjacent "send reminders" (`sendDuesReminders` import at line 26) — leave as-is; the sub-page is the detail view.
4. `screen-meta.ts`: delete nav items `:70` and `:79`; move their `SCREEN_META` entries to the new keys `"/admin/reports/session-economics"` and `"/admin/reports/dues"` (breadcrumbs `["Admin","Money","Reports",…]`, matching `:128-130` style). The Reports nav item's `startsWith("/admin/reports")` match already highlights the new children.
5. e2e: update `/admin/dues` rows in `admin-shell.spec.ts:82` and `saas-launch-route-matrix.spec.ts:103` to the new URL (or assert the redirect); keep the `dues-followup` network stubs. Add/point any session-economics coverage at the new path. Keep testids `admin-dues` / `admin-session-economics` unchanged.

## Files to change / delete
- `frontend/app/(admin)/admin/reports/session-economics/page.tsx` (moved)
- `frontend/app/(admin)/admin/reports/dues/page.tsx` (moved)
- `frontend/app/(admin)/admin/session-economics/page.tsx` (→ redirect stub)
- `frontend/app/(admin)/admin/dues/page.tsx` (→ redirect stub)
- `frontend/app/(admin)/admin/reports/page.tsx` (2 new report cards)
- `frontend/components/admin/screen-meta.ts`
- `frontend/e2e/specs/admin-shell.spec.ts`, `frontend/e2e/specs/saas-launch-route-matrix.spec.ts`

## Verification
`pnpm typecheck && pnpm lint && pnpm e2e`. Note QW6: local typecheck may trip on stale `.next/types` after route moves — `rm -rf .next` first. Manually: old URLs redirect; dues reminder send + topbar action still work under `/admin/reports/dues`. Backend untouched (`dues-followup`, `session-economics` APIs unchanged) — audit-inventory manifest backend-side unaffected. UIM3 (funnel/attendance/utilization reports) lands on this same hub — coordinate card ordering.

## Risks / rollback
- Route moves invalidate stale `.next/types` locally (known QW6 issue), not a real failure.
- Dues is mutation-bearing; verify reminder mutation invalidation still targets `["admin","dues-followup"]` post-move (no key changes made).
- Rollback: revert restores old routes; redirect stubs are additive.

## PR checklist
- [x] Release note: "Session economics and Dues follow-up now live under Reports (old URLs redirect)"
- [x] TRACKER.md: UIC3 → DONE + PR link
- [x] This plan: Status → DONE (PR #NNN, date)
